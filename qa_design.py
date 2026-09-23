"""Independent V4 design gates (C6.7, C9.1, the C4.1 re-flow) on data/city-design.json.

Reads the page data (data/city-design.json, or a path given on the command line) plus data/layout.json,
rebuilds what the page data leaves out the way the viewer does (turn arcs from their fillets, the tour
polyline from its graph steps) and recomputes every gate from that geometry alone. It shares no code
with the solver (design.py); qa_world.py --phase v4 runs it as verify_design_v4().

  python qa_design.py [design.json]      run the gates, print a table, exit 1 on any failure
  python qa_design.py --control          positive control: for every gate, break the design on purpose in
                                         a throwaway copy and show that the gate goes red
"""
import argparse
import bisect
import copy
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# C6.1 reference pairs (district keys), C6.3 and C9 numbers.
C61 = [("core", "episodic"), ("core", "jhon"), ("core", "prasma"), ("episodic", "prospective"),
       ("episodic", "branding"), ("semantic", "branding"), ("procedural", "onebrain"), ("procedural", "jhon"),
       ("procedural", "prospective"), ("semantic", "prasma"), ("inbox", "semantic"), ("working", "jhon"),
       ("working", "reef"), ("prasma", "reef")]
STEP = 0.1
GRADE = 0.12
VCURV = 0.15          # deck vertical curvature cap per unit (a crest radius of 6.7), measured on the published points
FOOT = 0.20
SEP_H, SEP_V = 0.5, 0.6
FILLET_MIN = 0.9
CONT = 0.02
OWN = 2.0
ROAD_HALF, SIDEWALK = 0.44, 0.13
LANE_BRIDGE = ROAD_HALF + 0.04     # walkers on a bridge sidewalk
LAKE_RING, LAKE_BRIDGE = 1.5, 1.0
LOOP_GAP_DEG = 30.0   # a leaf is looped when the tour covers its ring with no angular gap above this
FURNITURE_R = {"table": 0.06, "chair": 0.035, "crate": 0.05, "cart": 0.12, "bin": 0.04, "kiosk": 0.14,
               "busstop": 0.16}


# ------------------------------------------------------------------ small geometry
def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - ax - dx * t, py - ay - dy * t), t


def resample(points, step=STEP, closed=False):
    """Linear resampling of an [x, y, (z)] polyline every `step` (and its last point)."""
    pts = [list(p) + ([0.0] if len(p) == 2 else []) for p in points]
    if closed:
        pts = pts + [pts[0]]
    out, carry = [], 0.0
    s_total = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a[:2], b[:2])
        if seg == 0:
            continue
        t = carry
        while t < seg - 1e-12:
            f = t / seg
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f,
                        s_total + t, -(b[1] - a[1]) / seg, (b[0] - a[0]) / seg))
            t += step
        carry = t - seg
        s_total += seg
    if not closed:
        a, b = pts[-2], pts[-1]
        seg = math.dist(a[:2], b[:2]) or 1
        out.append((b[0], b[1], b[2], s_total, -(b[1] - a[1]) / seg, (b[0] - a[0]) / seg))
    return out, s_total


def arclen(points, closed=False):
    pts = list(points) + ([points[0]] if closed else [])
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.dist(a[:2], b[:2]))
    return cum


def project(points, x, y, closed=False):
    """(distance, arc length) of the nearest point of a polyline."""
    pts = list(points) + ([points[0]] if closed else [])
    best, s = (math.inf, 0.0), 0.0
    for a, b in zip(pts, pts[1:]):
        d, t = seg_dist(x, y, a[0], a[1], b[0], b[1])
        L = math.dist(a[:2], b[:2])
        if d < best[0]:
            best = (d, s + t * L)
        s += L
    return best


def signed_area(points):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))


class Grid:
    def __init__(self, cell=2.0):
        self.cell, self.cells = cell, {}

    def add(self, item, x0, y0, x1, y1):
        c = self.cell
        for i in range(math.floor(x0 / c), math.floor(x1 / c) + 1):
            for j in range(math.floor(y0 / c), math.floor(y1 / c) + 1):
                self.cells.setdefault((i, j), []).append(item)

    def near(self, x, y):
        return self.cells.get((math.floor(x / self.cell), math.floor(y / self.cell)), ())


class World:
    """Everything the gates measure against, rebuilt from the published JSON."""

    def __init__(self, design, layout):
        self.d, self.layout = design, layout
        self.D = layout["districts"]
        z = {k: p["z"] for k, p in self.D.items()}
        dist = {}
        for n in json.loads((ROOT / "data" / "vault-city.json").read_text(encoding="utf-8"))["nodes"]:
            dist[str(n["id"])] = n["district"]
        self.boxes = Grid(1.0)
        self.far = Grid(4.0)
        for key, f in design["buildings"].items():
            x, y = layout["pos"][key]
            hw, hd = f["w"] * 0.57, f["d"] * 0.57
            base = z[dist[key]]
            box = (x, y, hw, hd, base, base + f["h"] * 1.08 + 0.14)
            self.boxes.add(box, x - hw - 1.2, y - hd - 1.2, x + hw + 1.2, y + hd + 1.2)
            self.far.add(box, x, y, x, y)
        # Road centrelines: closed routes (minus a shared stretch), open links, bridges.
        self.roads = Grid(2.0)
        self.route_pts = []
        for i, r in enumerate(design["routes"]):
            half = self.route_half(i)
            pts = [list(p) for p in r["points"]]
            closed = True
            if r.get("shared"):
                cut, s, keep = r["shared"][0]["from"], 0.0, [pts[0]]
                for a, b in zip(pts, pts[1:]):
                    s += math.dist(a, b)
                    if s <= cut + 1e-3:
                        keep.append(b)
                pts, closed = keep, False
            self.route_pts.append(pts)
            ring = pts + ([pts[0]] if closed else [])
            for a, b in zip(ring, ring[1:]):
                self._road(("route", i), a, b, r["z"], r["z"], half)
        for k, st in enumerate(design.get("streets", [])):
            for a, b in zip(st["points"], st["points"][1:]):
                self._road(("street", k), a, b, st["z"], st["z"], st["width"] / 2)
        for b in design["bridges"]:
            for p, q in zip(b["points"], b["points"][1:]):
                self._road(("bridge", b["id"]), p, q, p[2], q[2], b["width"] / 2)

    def route_half(self, i):
        r = self.d["routes"][i]
        return r.get("width", 0.54 if r["district"] == "episodic" else 0.88) / 2

    def _road(self, owner, a, b, za, zb, half):
        r = 2.4
        self.roads.add((owner, a[0], a[1], b[0], b[1], za, zb, half),
                       min(a[0], b[0]) - r, min(a[1], b[1]) - r, max(a[0], b[0]) + r, max(a[1], b[1]) + r)

    def foot(self, x, y):
        best = 1.2
        for bx, by, hw, hd, _, _ in self.boxes.near(x, y):
            best = min(best, math.hypot(max(0.0, abs(x - bx) - hw), max(0.0, abs(y - by) - hd)))
        return best

    def foot_exact(self, x, y, reach=3):
        """Distance to the nearest footprint within reach x 4 units (no cap below that)."""
        best = math.inf
        gx, gy = math.floor(x / 4), math.floor(y / 4)
        for i in range(gx - reach, gx + reach + 1):
            for j in range(gy - reach, gy + reach + 1):
                for bx, by, hw, hd, _, _ in self.far.cells.get((i, j), ()):
                    best = min(best, math.hypot(max(0.0, abs(x - bx) - hw), max(0.0, abs(y - by) - hd)))
        return best

    def blocked(self, x, y, z, r):
        for bx, by, hw, hd, base, top in self.boxes.near(x, y):
            if base - 0.1 < z < top and abs(x - bx) < hw + r and abs(y - by) < hd + r:
                return True
        return False

    def plateau(self, x, y):
        for k, p in self.D.items():
            if p["shape"] == "disc" and math.hypot(x - p["cx"], y - p["cy"]) < p["rx"]:
                return k
            if p["shape"] == "rect" and abs(x - p["cx"]) < p["rx"] and abs(y - p["cy"]) < p["ry"]:
                return k
        return None

    def ring_route(self, district):
        p = self.D[district]
        for i, r in enumerate(self.d["routes"]):
            if r["district"] == district and (p["shape"] == "disc" or r.get("kind") == "rim"):
                return i
        raise KeyError(district)

    def route_dist(self, i, x, y):
        pts = self.route_pts[i]
        closed = not self.d["routes"][i].get("shared")
        ring = pts + ([pts[0]] if closed else [])
        return min(seg_dist(x, y, a[0], a[1], b[0], b[1])[0] for a, b in zip(ring, ring[1:]))


def ellipse(lake):
    """Shore samples and an exact signed shore distance (nearest of 720 samples, refined)."""
    c, s = math.cos(lake["angle"]), math.sin(lake["angle"])
    a, b = lake["rx"], lake["ry"]
    pts = []
    for i in range(720):
        t = i * math.tau / 720
        u, v = a * math.cos(t), b * math.sin(t)
        pts.append((lake["cx"] + u * c - v * s, lake["cy"] + u * s + v * c))

    def gap(x, y):
        dx, dy = x - lake["cx"], y - lake["cy"]
        u, v = dx * c + dy * s, -dx * s + dy * c
        f = lambda t: (a * math.cos(t) - u) ** 2 + (b * math.sin(t) - v) ** 2
        i0 = min(range(720), key=lambda i: f(i * math.tau / 720))
        lo, hi = (i0 - 1) * math.tau / 720, (i0 + 1) * math.tau / 720
        for _ in range(30):
            m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
            lo, hi = (lo, m2) if f(m1) < f(m2) else (m1, hi)
        d = math.sqrt(f((lo + hi) / 2))
        return -d if (u / a) ** 2 + (v / b) ** 2 < 1 else d

    def lower(x, y):
        return math.hypot(x - lake["cx"], y - lake["cy"]) - a
    return pts, gap, lower


def arc(f, radius=None, step=0.05):
    r = f["r"] if radius is None else radius
    n = max(2, math.ceil(abs(math.radians(f["a1"] - f["a0"])) * r / step))
    return [(f["cx"] + r * math.cos(math.radians(f["a0"] + (f["a1"] - f["a0"]) * j / n)),
             f["cy"] + r * math.sin(math.radians(f["a0"] + (f["a1"] - f["a0"]) * j / n))) for j in range(n + 1)]


def viewer_lamps(route, width):
    """city-life.js:177: from d = 1.5 every 4.6 (Archive) or 3.8, offset width/2 + 0.07 on the left."""
    pts = route["points"]
    cum = arclen(pts, closed=True)
    step = 4.6 if route["district"] == "episodic" else 3.8
    out, d, j = [], 1.5, 0
    while d < cum[-1]:
        while cum[j + 1] < d:
            j += 1
        a, b = pts[j], pts[(j + 1) % len(pts)]
        L = math.dist(a, b) or 1
        t = (d - cum[j]) / L
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        off = width / 2 + 0.07
        out.append((x - (b[1] - a[1]) / L * off, y + (b[0] - a[0]) / L * off, d))
        d += step
    return out


# ------------------------------------------------------------------ the page data, rebuilt
# The contract (design.py publish()): graph node ids are indices and their ports every edge end in edge
# order; a bridge edge's from, to and split are its bridge's; a turn's node is its bridge end's node and
# its points the arc of radius r + 0.44 through its fillet from a0 to a1 in steps of 0.1 or less; the
# tour polyline joins each step's turn arc and trimmed edge and is resampled from s0 in count steps.
def arc_deg(cx, cy, r, a0, a1, step):
    n = max(2, math.ceil(abs(math.radians(a1 - a0)) * r / step))
    return [[cx + r * math.cos(math.radians(a0 + (a1 - a0) * j / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * j / n))] for j in range(n + 1)]


def point_at(points, cum, s):
    """Point at arc length s on an open polyline with cumulative lengths cum (s clamped)."""
    s = max(0.0, min(cum[-1], s))
    i = max(0, min(len(cum) - 2, bisect.bisect_right(cum, s) - 1))
    t = (s - cum[i]) / ((cum[i + 1] - cum[i]) or 1e-12)
    return [points[i][q] + (points[i + 1][q] - points[i][q]) * t for q in range(len(points[i]))]


def loop_slice(points, s0, s1, z):
    """A closed route's centreline between arc lengths s0 < s1 (s1 may pass the loop end), as [x, y, z]."""
    ring = [list(p) for p in points] + [list(points[0])]
    cum = arclen(points, closed=True)
    total = cum[-1]
    out = [point_at(ring, cum, s0 % total) + [z]]
    base, k = s0 - (s0 % total), bisect.bisect_right(cum, s0 % total)
    while True:
        if k >= len(points):
            k, base = 0, base + total
        if base + cum[k] >= s1 - 1e-9:
            break
        out.append([points[k][0], points[k][1], z])
        k += 1
    last = s1 - total * math.floor(s1 / total) if s1 > total else s1
    out.append(point_at(ring, cum, last) + [z])
    return out


def trim(points, lo, hi):
    cum = arclen(points)
    lo, hi = max(0.0, lo), min(cum[-1], hi)
    return ([point_at(points, cum, lo)] + [list(p) for p, c in zip(points, cum) if lo + 1e-9 < c < hi - 1e-9]
            + [point_at(points, cum, hi)])


def expand(page):
    """The design rebuilt from the page data."""
    d = copy.deepcopy(page)
    bridges = d["bridges"]
    for b in bridges:
        b.setdefault("spoke", b["from"] == "core")
        b.setdefault("halfWidth", round(b["width"] / 2 + b["sidewalk"], 3))
        for e in b["ends"]:
            for f in e["fillets"]:
                f.setdefault("ring", [f["cx"] + f["r"] * math.cos(math.radians(f["a0"])),
                                      f["cy"] + f["r"] * math.sin(math.radians(f["a0"]))])
                f.setdefault("bridge", [f["cx"] + f["r"] * math.cos(math.radians(f["a1"])),
                                        f["cy"] + f["r"] * math.sin(math.radians(f["a1"]))])
    g = d["graph"]
    for k, n in enumerate(g["nodes"]):
        n["id"], n["ports"] = k, []
    for k, e in enumerate(g["edges"]):
        e["id"] = k
        g["nodes"][e["a"]]["ports"].append([k, 0])
        g["nodes"][e["b"]]["ports"].append([k, 1])
        if e["kind"] == "bridge":
            b = bridges[e["bridge"]]
            e["from"], e["to"], e["split"] = b["from"], b["to"], b["split"]
    for k, t in enumerate(g["turns"]):
        end = bridges[t["bridge"]]["ends"][t["end"]]
        f = next(f for f in end["fillets"] if f["side"] == t["side"])
        t["id"], t["node"] = k, end["node"]
        t["points"] = [p + [end["z"]] for p in arc_deg(f["cx"], f["cy"], f["r"] + ROAD_HALF, f["a0"], f["a1"], 0.1)]
        t["length"] = arclen(t["points"])[-1]
    tour = d["tour"]
    if "points" not in tour:
        dense = []

        def add(points):
            for p in points:
                if not dense or math.dist(dense[-1][:2], p[:2]) >= 1e-6:
                    dense.append(p)
        steps = tour["steps"]
        for i, (edge, frm, turn, tdir) in enumerate(steps):
            e, nxt = g["edges"][edge], steps[(i + 1) % len(steps)]
            key = "trimBridge" if e["kind"] == "bridge" else "trimRing"
            if turn >= 0:
                pts = [list(p) for p in g["turns"][turn]["points"]]
                add(pts if tdir > 0 else pts[::-1])
            if e["kind"] == "bridge":
                pts = [list(p) for p in bridges[e["bridge"]]["points"]]
            elif e["kind"] == "link":
                st = d["streets"][e["street"]]
                pts = [[x, y, st["z"]] for x, y in st["points"]]
            else:
                r = d["routes"][e["route"]]
                pts = loop_slice(r["points"], e["s0"], e["s1"], r["z"])
            if frm == 1:
                pts = pts[::-1]
            lo = g["turns"][turn][key] if turn >= 0 else 0.0
            hi = arclen(pts)[-1] - (g["turns"][nxt[2]][key] if nxt[2] >= 0 else 0.0)
            add(trim(pts, lo, hi))
        if math.dist(dense[-1][:2], dense[0][:2]) < 1e-6:
            dense.pop()
        ring = dense + [dense[0]]
        rcum = arclen(ring)
        total = rcum[-1]
        tour["points"] = [point_at(ring, rcum, (tour["s0"] + total * k / tour["count"]) % total)
                          for k in range(tour["count"])]
    entries = tour["entries"]
    tour.setdefault("spans", [{"district": en["district"], "from": en["s"],
                               "to": entries[i + 1]["s"] if i + 1 < len(entries) else tour["length"]}
                              for i, en in enumerate(entries)])
    return d


# ------------------------------------------------------------------ the gates
def run(design, layout, quiet=False):
    W = World(design, layout)
    res = {}

    def gate(name, ok, measured):
        res[name] = (bool(ok), measured)

    bridges = design["bridges"]
    by_id = {b["id"]: b for b in bridges}
    routes = design["routes"]
    # 1. Fourteen bridges on the C6.1 pairs.
    pairs = sorted(tuple(sorted((b["from"], b["to"]))) for b in bridges)
    gate("bridges: 14 on the C6.1 pairs", len(bridges) == 14 and pairs == sorted(tuple(sorted(p)) for p in C61),
         f"{len(bridges)} bridges, pairs match C6.1: {pairs == sorted(tuple(sorted(p)) for p in C61)}")

    # 2. The graph is connected; bridge edges join their districts' rings.
    g = design["graph"]
    nodes, edges, turns = g["nodes"], g["edges"], g["turns"]
    edge_by = {e["id"]: e for e in edges}
    adj = {n["id"]: set() for n in nodes}
    ok_ends = True
    for e in edges:
        if e["a"] not in adj or e["b"] not in adj:
            ok_ends = False
            continue
        adj[e["a"]].add(e["b"])
        adj[e["b"]].add(e["a"])
        if e["kind"] == "bridge":
            b = by_id.get(e["bridge"])
            da, db = nodes[e["a"]]["district"], nodes[e["b"]]["district"]
            ok_ends &= b is not None and {da, db} == {b["from"], b["to"]}
    seen, todo = set(), [nodes[0]["id"]] if nodes else []
    while todo:
        k = todo.pop()
        if k not in seen:
            seen.add(k)
            todo += list(adj[k] - seen)
    districts_in = {nodes[k]["district"] for k in seen}
    bridge_edges = sum(1 for e in edges if e["kind"] == "bridge")
    gate("graph: one connected component", len(seen) == len(adj) and ok_ends and bridge_edges == len(bridges),
         f"{len(seen)} of {len(adj)} nodes reached, {len(edges)} edges ({bridge_edges} bridges), "
         f"{len(districts_in)} districts in the component, bridge ends on their rings: {ok_ends}")
    gate("graph: every district reachable", len(districts_in) == 12, f"{len(districts_in)} districts")

    # 2b. Turns: each turn arc runs from the right side of its ring to its bridge; each move uses the
    # turn on the side it drives, in the direction it drives; every tee has 4 turning moves on 2 arcs.
    def end_node(e, end):
        return e["a"] if end == 0 else e["b"]
    turn_err, arc_err, tee_err = [], 0.0, []
    route_cum = {}
    for t in turns:
        node = nodes[t["node"]]
        b = by_id.get(t["bridge"])
        if b is None:
            turn_err.append(f"turn {t['id']} names no bridge")
            continue
        end = b["ends"][t["end"]]
        ri = end["route"]
        if ri not in route_cum:
            route_cum[ri] = arclen(routes[ri]["points"], closed=True)
        total = route_cum[ri][-1]
        p0, p1 = t["points"][0], t["points"][-1]
        d0, s0 = project(routes[ri]["points"], p0[0], p0[1], closed=True)
        delta = ((s0 - end["s"] + total / 2) % total) - total / 2
        bpts = b["points"] if t["end"] == 0 else b["points"][::-1]
        d1, s1 = project(bpts, p1[0], p1[1])
        arc_err = max(arc_err, d0, d1, abs(abs(delta) - t["trimRing"]), abs(s1 - t["trimBridge"]))
        if (1 if delta > 0 else -1) != t["ringSide"]:
            turn_err.append(f"turn {t['id']} ringSide {t['ringSide']} but its ring point is at delta {delta:.2f}")
        if abs(node["x"] - end["x"]) > 1e-3 or abs(node["y"] - end["y"]) > 1e-3:
            turn_err.append(f"turn {t['id']} node is not its bridge end")
    for node in nodes:
        used = []
        for m in node["moves"]:
            ein, eout = edge_by.get(m[0]), edge_by.get(m[2])
            if ein is None or eout is None or end_node(ein, m[1]) != node["id"] or end_node(eout, m[3]) != node["id"]:
                turn_err.append(f"node {node['id']} move {m[:4]} does not meet at the node")
                continue
            is_turn = (ein["kind"] == "bridge") != (eout["kind"] == "bridge")
            if m[4] < 0:
                if is_turn:
                    turn_err.append(f"node {node['id']} move {m[:4]} changes ring and bridge without a turn arc")
                continue
            if not is_turn or m[4] >= len(turns):
                turn_err.append(f"node {node['id']} move {m[:4]} names a turn it cannot use")
                continue
            t = turns[m[4]]
            ring_e, bridge_e = (eout, ein) if ein["kind"] == "bridge" else (ein, eout)
            want_dir = -1 if ein["kind"] == "bridge" else 1
            # The ring side a move drives: arriving at the ring edge's b end (or leaving from its a end)
            # uses the ring at larger s from the tee only when leaving from a or arriving at a.
            side = (1 if m[1] == 0 else -1) if want_dir == 1 else (1 if m[3] == 0 else -1)
            if t["node"] != node["id"] or t["bridge"] != bridge_e.get("bridge") or m[5] != want_dir or t["ringSide"] != side:
                turn_err.append(f"node {node['id']} move {m[:4]} uses turn {m[4]} (side {t['ringSide']}, dir {m[5]}), "
                                f"needs side {side}, dir {want_dir}")
            used.append((m[4], m[5]))
        if node["kind"] == "tee":
            if len(used) != 4 or len({u[0] for u in used}) != 2 or sorted(used) != sorted(
                    [(u, d) for u in {u[0] for u in used} for d in (1, -1)]):
                tee_err.append(node["id"])
    n_turn_moves = sum(1 for n in nodes for m in n["moves"] if m[4] >= 0)
    gate("graph: every tee turns both ways, each move on its own turn arc",
         not turn_err and not tee_err and arc_err <= 0.05 and n_turn_moves == 8 * len(bridges),
         f"{n_turn_moves} turning moves on {len(turns)} turn arcs, arc endpoint error {arc_err:.3f}, "
         f"{len(turn_err)} move or side errors, {len(tee_err)} tees without 4 moves on 2 arcs"
         + (f"; first: {turn_err[0]}" if turn_err else ""))

    # 2c. The move graph: every drivable state (an edge, arrived at one end) reaches every other.
    fwd, back = {}, {}
    states = {(e["id"], end) for e in edges for end in (0, 1)}
    for node in nodes:
        for m in node["moves"]:
            a, b2 = (m[0], m[1]), (m[2], 1 - m[3])
            fwd.setdefault(a, set()).add(b2)
            back.setdefault(b2, set()).add(a)

    def reach(start, nxt):
        got, stack = {start}, [start]
        while stack:
            for q in nxt.get(stack.pop(), ()):
                if q not in got:
                    got.add(q)
                    stack.append(q)
        return got
    first = min(states)
    f_reach, b_reach = reach(first, fwd), reach(first, back)
    gate("graph: every drivable state reaches every other (moves strongly connected)",
         f_reach >= states and b_reach >= states,
         f"{len(states & f_reach)} of {len(states)} states reached forward, {len(states & b_reach)} backward")

    # 3 to 6. Per bridge, sampled every 0.1.
    worst = {"grade": 0.0, "vcurv": 0.0, "foot": 9.0, "raw": 0, "cam": 0, "lane": 0, "sep": 9.0, "plateau": 0,
             "cont": 0.0, "fillet_r": 9.0, "tangent": 0.0, "camdeck": 0, "hmin": 9.0, "vmin": 9.0, "over": {},
             "stack": []}
    detail = {"grade": "", "foot": "", "sep": "", "vcurv": ""}
    samples_all = 0
    exact_clear = {}
    for b in bridges:
        smp, L = resample(b["points"])
        samples_all += len(smp)
        # grade
        for p, q in zip(smp, smp[1:]):
            ds = q[3] - p[3]
            if ds > 1e-9:
                gr = abs(q[2] - p[2]) / ds
                if gr > worst["grade"]:
                    worst["grade"], detail["grade"] = gr, f"{b['name']} at s={p[3]:.1f}"
        # vertical curvature, on the published points (three-point second difference)
        P = b["points"]
        for i in range(1, len(P) - 1):
            h1, h2 = math.dist(P[i - 1][:2], P[i][:2]), math.dist(P[i][:2], P[i + 1][:2])
            if h1 > 1e-6 and h2 > 1e-6:
                k = abs(2 * ((P[i + 1][2] - P[i][2]) / h2 - (P[i][2] - P[i - 1][2]) / h1) / (h1 + h2))
                if k > worst["vcurv"]:
                    worst["vcurv"], detail["vcurv"] = k, f"{b['name']} at point {i}"
        # footprints (the street check), then the ring-level QA points and the walking lanes on the sidewalk
        clear = min(W.foot(x, y) for x, y, *_ in smp)
        exact_clear[b["id"]] = min(W.foot_exact(x, y) for x, y, *_ in smp)
        if clear < worst["foot"]:
            worst["foot"], detail["foot"] = clear, b["name"]
        for x, y, z, s, nx, ny in smp:
            worst["raw"] += W.blocked(x, y, z + 0.64, 0.14)
            worst["cam"] += W.blocked(x, y, z + 0.32, 0.14)
            for side in (-1, 1):
                worst["lane"] += W.blocked(x + side * LANE_BRIDGE * nx, y + side * LANE_BRIDGE * ny, z + 0.18, 0.07)
            worst["plateau"] += W.plateau(x, y) is not None
        # separation from other rings, links and bridges: 0.5 horizontally or 0.6 above
        own = {(b["ends"][0]["route"], 0), (b["ends"][1]["route"], 1)}
        for x, y, z, s, _, _ in smp:
            for owner, ax, ay, bx, by, za, zb, half in W.roads.near(x, y):
                if owner == ("bridge", b["id"]):
                    continue
                if owner[0] == "route" and ((owner[1], 0) in own and s < OWN or (owner[1], 1) in own and L - s < OWN):
                    continue
                d, t = seg_dist(x, y, ax, ay, bx, by)
                gap = d - 0.57 - (half + 0.13)
                zo = za + (zb - za) * t
                # Over a ring the bridge must be the upper deck; two bridges may cross either way.
                vertical = abs(z - zo) if owner[0] == "bridge" else z - zo
                if gap < SEP_H and vertical >= SEP_V:
                    worst["vmin"] = min(worst["vmin"], vertical)
                    o = worst["over"].setdefault((b["id"], owner), [9.0, s, s])
                    o[0], o[1], o[2] = min(o[0], vertical), min(o[1], s), max(o[2], s)
                    # one walkable height per plan point: the deck (to its sidewalk edge) never over
                    # another road's paved band
                    if gap < 0:
                        worst["stack"].append((b["id"], owner, round(s, 2), round(gap, 3)))
                elif gap >= 0 and vertical < SEP_V:
                    worst["hmin"] = min(worst["hmin"], gap)
                if gap < SEP_H and vertical < SEP_V:
                    if gap < worst["sep"]:
                        worst["sep"], detail["sep"] = gap, f"{b['name']} vs {owner} at s={s:.1f}"
                # chase camera under an overpass: the camera must stay below the other deck's underside
                if owner[0] == "bridge" and d < half + 0.13 and 0 < zo - z < 0.32 + 0.14 + 0.12:
                    worst["camdeck"] += 1
        # The junction corners count as deck too: a fillet's paved corner (between its carriageway-edge
        # arc and its curb) never lies over another road's paved band.
        for ei, end in enumerate(b["ends"]):
            for f in end["fillets"]:
                for x, y in arc(f) + arc(f, f["r"] - 0.13):
                    for owner, ax, ay, bx, by, za, zb, half in W.roads.near(x, y):
                        if owner == ("route", end["route"]) or owner == ("bridge", b["id"]):
                            continue
                        d, t = seg_dist(x, y, ax, ay, bx, by)
                        if d < half + 0.13:
                            worst["stack"].append((b["id"], owner, "fillet", round(d - half - 0.13, 3)))
        # junction continuity and fillets
        for ei, end in enumerate(b["ends"]):
            zr = routes[end["route"]]["z"]
            first = b["points"][0] if ei == 0 else b["points"][-1]
            worst["cont"] = max(worst["cont"], abs(first[2] - zr))
            for f in end["fillets"]:
                worst["fillet_r"] = min(worst["fillet_r"], f["r"])
                s_t = f["bridgeS"] if ei == 0 else L - f["bridgeS"]
                zt = min(smp, key=lambda p: abs(p[3] - s_t))[2]
                worst["cont"] = max(worst["cont"], abs(zt - zr))
                # tangency: centre at r + 0.44 from both centrelines, never closer to the bridge
                d_ring = W.route_dist(end["route"], f["cx"], f["cy"])
                d_bridge = min(math.hypot(x - f["cx"], y - f["cy"]) for x, y, *_ in smp)
                worst["tangent"] = max(worst["tangent"], abs(d_ring - f["r"] - 0.44), abs(d_bridge - f["r"] - 0.44),
                                       abs(math.dist(f["ring"], (f["cx"], f["cy"])) - f["r"]),
                                       abs(math.dist(f["bridge"], (f["cx"], f["cy"])) - f["r"]))
    gate("grade <= 12 % every 0.1", worst["grade"] <= GRADE + 1e-9, f"max {worst['grade'] * 100:.2f} % ({detail['grade']})")
    gate("deck vertical curvature <= 0.15 per unit (no speed bumps)", worst["vcurv"] <= VCURV,
         f"max {worst['vcurv']:.3f} ({detail['vcurv']})")
    gate("deck centreline >= 0.20 from footprints", worst["foot"] >= FOOT, f"min {worst['foot']:.3f} ({detail['foot']}), {samples_all} samples")
    gate("deck point +0.64 clear (r 0.14)", worst["raw"] == 0, f"{worst['raw']} blocked samples")
    gate("chase camera +0.32 clear (r 0.14)", worst["cam"] == 0, f"{worst['cam']} blocked samples")
    gate("both walking lanes on the sidewalk (0.48) +0.18 clear (r 0.07)", worst["lane"] == 0, f"{worst['lane']} blocked samples")
    gate("no deck over a plateau", worst["plateau"] == 0, f"{worst['plateau']} samples over a plateau")
    pairs_over = sorted((bid, o[0], o[1], round(v[0], 3), round(v[1], 2), round(v[2], 2)) for (bid, o), v in worst["over"].items())
    gate("0.5 horizontal or 0.6 overpass from rings, links, bridges", worst["sep"] >= SEP_H,
         (f"VIOLATION gap {worst['sep']:.3f} ({detail['sep']}); " if worst["sep"] < SEP_H else "") +
         f"min horizontal gap {worst['hmin']:.3f}, {len(pairs_over)} overpasses (bridge, road, vertical, s from, s to) "
         f"{pairs_over}")
    gate("one walkable height per plan point: no deck or junction corner over another road's paved band", not worst["stack"],
         f"{len(worst['stack'])} samples stacked" + (f", first {worst['stack'][0]}" if worst["stack"] else ""))
    gate("chase camera under no overpass deck", worst["camdeck"] == 0, f"{worst['camdeck']} samples")
    gate("junction continuity <= 0.02", worst["cont"] <= CONT, f"max {worst['cont']:.4f}")
    gate("fillet radius >= 0.9, tangent both sides", worst["fillet_r"] >= FILLET_MIN and worst["tangent"] <= 0.02,
         f"min r {worst['fillet_r']}, max tangency error {worst['tangent']:.4f}, {sum(len(e['fillets']) for b in bridges for e in b['ends'])} fillets")

    # The new streets pass the ring street checks too: the rim road on its own stretch at its own width
    # (lanes on the sidewalk at 0.48), the rim links at theirs (0.31).
    new_roads = []
    for i, r in enumerate(routes):
        if r.get("kind") == "rim":
            new_roads.append((r["name"], W.route_pts[i], r["z"], False, r.get("width", 0.88)))
    new_roads += [(s["name"], s["points"], s["z"], False, s["width"]) for s in design.get("streets", [])]
    bad, minc, measured = 0, 9.0, {}
    for name, pts, z, closed, width in new_roads:
        smp, _ = resample(pts, closed=closed)
        c = min(W.foot(x, y) for x, y, *_ in smp)
        measured[name] = min(W.foot_exact(p[0], p[1]) for p in pts)
        minc = min(minc, c)
        lane = width / 2 + 0.04
        for x, y, _, s, nx, ny in smp:
            bad += W.blocked(x, y, z + 0.64, 0.14)
            for side in (-1, 1):
                bad += W.blocked(x + side * lane * nx, y + side * lane * ny, z + 0.18, 0.07)
    gate("rim road (own stretch) and links pass the street checks", minc >= FOOT and bad == 0,
         f"min centreline clearance {minc:.3f}, {bad} blocked samples (lanes on the sidewalk), {len(new_roads)} roads")

    # Routes run counterclockwise (the viewer puts lamps on the left, which must be the plateau side),
    # and the viewer's lamps (city-life.js rule, at the viewer's width and at route.width) never stand
    # on a bridge deck or a junction corner beyond the ring's own carriageway.
    cw = [i for i, r in enumerate(routes) if signed_area(r["points"]) <= 0]
    deck_pts = []
    for b in bridges:
        for p in b["points"]:
            own = [e["route"] for e in b["ends"]]
            if all(W.route_dist(ri, p[0], p[1]) > ROAD_HALF for ri in own):
                deck_pts.append((p[0], p[1], p[2], 0.57))
    for t in turns:
        ri = by_id[t["bridge"]]["ends"][t["end"]]["route"] if t["bridge"] in by_id else None
        for p in t["points"]:
            if ri is not None and W.route_dist(ri, p[0], p[1]) > ROAD_HALF:
                deck_pts.append((p[0], p[1], p[2], 0.57))
    lamp_grid = Grid(2.0)
    for x, y, z, half in deck_pts:
        lamp_grid.add((x, y, z, half), x - 1, y - 1, x + 1, y + 1)
    lamp_hits = []
    for i, r in enumerate(routes):
        widths = {0.54 if r["district"] == "episodic" else 0.88, r.get("width", 0.88 if r["district"] != "episodic" else 0.54)}
        for width in sorted(widths):
            for x, y, d in viewer_lamps(r, width):
                for px, py, pz, half in lamp_grid.near(x, y):
                    if math.hypot(x - px, y - py) < half + 0.06 and pz < r["z"] + 1.05 + 0.05:
                        lamp_hits.append((i, width, round(d, 2)))
                        break
    gate("routes run counterclockwise; viewer lamps never on a deck or junction corner",
         not cw and not lamp_hits,
         f"{len(cw)} clockwise routes {cw}, {len(lamp_hits)} lamps on a deck or corner"
         + (f", first {lamp_hits[0]}" if lamp_hits else ""))

    # 7. The tour.
    tour = design["tour"]
    tp = tour["points"]
    smp, total = resample(tp, closed=True)
    gaps = max(math.dist(a[:2], b[:2]) for a, b in zip(tp, tp[1:] + tp[:1]))
    visited = [e["district"] for e in tour["entries"]]
    gate("tour: closed walk from the Compass", tour["start"] == "core" and gaps <= 0.3 and abs(total - tour["length"]) < 0.5,
         f"length {total:.1f} (declared {tour['length']}), largest step {gaps:.3f}")
    gate("tour: visits all 12 districts", len(set(visited)) == 12, f"{len(set(visited))} districts, {len(visited)} entries")
    mono = all(a["s"] < b["s"] for a, b in zip(tour["entries"], tour["entries"][1:]))
    at_edge = 0.0
    for en in tour["entries"][1:]:
        k = min(range(len(smp)), key=lambda i: abs(smp[i][3] - en["s"]))
        at_edge = max(at_edge, abs(W.route_dist(W.ring_route(en["district"]), smp[k][0], smp[k][1]) - 0.57))
    gate("tour: entries in order, each on its ring edge", mono and at_edge <= 0.08,
         f"monotonic {mono}, worst entry off the 0.57 ring edge by {at_edge:.3f}")
    # Leaves: arrive and leave by the same bridge, and drive the whole ring in between.
    loop_note, loop_ok = [], True
    spans = tour["spans"]
    for leaf in ("onebrain", "inbox"):
        idx = [i for i, e in enumerate(tour["entries"]) if e["district"] == leaf]
        if not idx:
            loop_ok = False
            loop_note.append(f"{leaf} never entered")
            continue
        p = W.D[leaf]
        for i in idx:
            arrive = tour["entries"][i]["bridge"]
            leave = tour["entries"][i + 1]["bridge"] if i + 1 < len(tour["entries"]) else None
            lo, hi = spans[i]["from"], spans[i]["to"]
            ring_i = W.ring_route(leaf)
            angs = sorted(math.degrees(math.atan2(y - p["cy"], x - p["cx"])) % 360
                          for x, y, z, s, _, _ in smp if lo <= s <= hi and W.route_dist(ring_i, x, y) < 0.3)
            gap_deg = 360.0 if not angs else max([b2 - a2 for a2, b2 in zip(angs, angs[1:])] + [angs[0] + 360 - angs[-1]])
            loop_ok &= arrive == leave and gap_deg <= LOOP_GAP_DEG
            loop_note.append(f"{leaf} in by {arrive}, out by {leave}, widest gap round the ring {gap_deg:.1f} deg")
    gate("tour: leaves (Dome, Gate) looped round the ring and left by the same bridge", loop_ok, "; ".join(loop_note))
    off_road, cam, camdeck = 0, 0, 0
    for x, y, z, s, _, _ in smp:
        best, here = 9.0, None
        near = W.roads.near(x, y)
        for owner, ax, ay, bx, by, za, zb, half in near:
            d, t = seg_dist(x, y, ax, ay, bx, by)
            zo = za + (zb - za) * t
            if abs(zo - z) < 0.05 and d - half < best:
                best, here = d - half, owner
        for owner, ax, ay, bx, by, za, zb, half in near:
            if owner[0] != "bridge" or owner == here:
                continue
            d, t = seg_dist(x, y, ax, ay, bx, by)
            if d < half + 0.13 and 0.05 < za + (zb - za) * t - z < 0.32 + 0.14 + 0.12:
                camdeck += 1
        off_road += best > 0.03
        cam += W.blocked(x, y, z + 0.32, 0.14)
    gate("tour: every sample on a carriageway", off_road == 0, f"{off_road} of {len(smp)} samples off road")
    gate("tour: chase camera clear every 0.1", cam == 0 and camdeck == 0,
         f"{cam} samples inside a footprint, {camdeck} under an overpass deck")

    # 8. The lake, pier and island (C9.1, C9.4).
    lake = design["lake"][0]
    shore, gap, lower = ellipse(lake)
    reef = W.D["reef"]
    reef_outer = reef["rx"] + 0.4 + 0.57
    touch = min(math.hypot(x - reef["cx"], y - reef["cy"]) for x, y in shore) - reef_outer
    reef_route = W.ring_route("reef")

    def nearest(pts):
        best = math.inf
        for lb, x, y, off in sorted((lower(x, y) - off, x, y, off) for x, y, off in pts):
            if lb >= best:
                break
            best = min(best, gap(x, y) - off)
        return best
    ring_pts = [(x, y, W.route_half(i) + 0.13) for i, pts in enumerate(W.route_pts) if i != reef_route for x, y in pts]
    ring_pts += [(x, y, s["width"] / 2 + 0.13) for s in design.get("streets", []) for x, y in s["points"]]
    deck_edge = [(x, y, 0.57) for b in bridges for x, y, *_ in resample(b["points"], 0.2)[0]]
    deck_edge += [(x, y, 0.0) for b in bridges for e in b["ends"] for f in e["fillets"] for x, y in arc(f, f["r"] - 0.13)]
    ring_gap, bridge_gap = nearest(ring_pts), nearest(deck_edge)
    gate("lake: near shore on the Reef ring's outer sidewalk", abs(touch) <= 0.05, f"shore to sidewalk edge {touch:+.3f}")
    gate("lake: clears every other ring by 1.5", ring_gap >= LAKE_RING, f"min {ring_gap:.3f}")
    gate("lake: clears every bridge by 1.0", bridge_gap >= LAKE_BRIDGE, f"min {bridge_gap:.3f} (deck sidewalk edge or fillet curb)")
    pier, isl = lake["pier"], lake["island"]
    p_len = math.dist((pier["x0"], pier["y0"]), (pier["x1"], pier["y1"]))
    p_start = math.hypot(pier["x0"] - reef["cx"], pier["y0"] - reef["cy"]) - reef_outer
    p_end = math.dist((pier["x1"], pier["y1"]), (isl["x"], isl["y"])) - isl["r"]
    on_water = all(gap(pier["x0"] + (pier["x1"] - pier["x0"]) * t / 20, pier["y0"] + (pier["y1"] - pier["y0"]) * t / 20) < 0.01
                   for t in range(1, 21))
    isl_in = max(gap(isl["x"] + isl["r"] * math.cos(t * math.tau / 90), isl["y"] + isl["r"] * math.sin(t * math.tau / 90))
                 for t in range(90))
    reef_stage = next(s for s in design["stages"] if s["district"] == "reef")
    stage_on = abs(reef_stage["x"] - isl["x"]) < 1e-3 and abs(reef_stage["y"] - isl["y"]) < 1e-3 and reef_stage["r"] == isl["r"]
    gate("pier 0.5 x 5 from the Reef ring to a radius 2 island stage",
         pier["width"] == 0.5 and abs(p_len - 5) <= 0.01 and abs(p_start) <= 0.02 and abs(p_end) <= 0.02 and on_water
         and isl["r"] == 2 and isl_in < 0 and stage_on,
         f"length {p_len:.3f}, start off the sidewalk edge {p_start:+.3f}, end off the island {p_end:+.3f}, "
         f"over water {on_water}, island inside by {-isl_in:.2f}, Reef stage on the island {stage_on}")
    # The viewer's stage rule (society.js:36): a deck's booth sits at +angle, anything else at -angle.
    # On the island the booth must stand on the far side from the pier, so the crowd fills the floor
    # between the pier landing and the booth.
    rs = reef_stage
    face = 1 if rs["kind"] == "deck" else -1
    fx, fy = face * math.cos(rs["angle"]), face * math.sin(rs["angle"])
    booth = (rs["x"] + fx * rs["r"] * 0.6, rs["y"] + fy * rs["r"] * 0.6)
    landing = (pier["x1"], pier["y1"])
    to_land = ((landing[0] - rs["x"]) / rs["r"], (landing[1] - rs["y"]) / rs["r"])
    booth_gap = math.dist(booth, landing)
    gate("Reef island stage: booth on the far side from the pier (viewer rule)",
         fx * to_land[0] + fy * to_land[1] < -0.9 and booth_gap >= rs["r"],
         f"booth {booth_gap:.2f} from the pier landing, facing . pier direction {fx * to_land[0] + fy * to_land[1]:+.2f}")

    # 9. Stages (C4.2): one per district, clear of neighbour rings, bridges, fillets, the lake, the pier.
    stages = design["stages"]
    worst_s, why_s = 9.0, ""
    fillets = [(f, e["z"]) for b in bridges for e in b["ends"] for f in e["fillets"]]
    for s in stages:
        x, y, r = s["x"], s["y"], s["r"]
        checks = []
        for k, q in W.D.items():
            if k == s["district"]:
                continue
            if q["shape"] == "disc":
                checks.append((math.hypot(x - q["cx"], y - q["cy"]) - (q["rx"] + (0.75 if k == "onebrain" else 0.4) + 0.57) - r, f"ring {k}"))
            else:
                dx = max(0, abs(x - q["cx"]) - q["rx"] - 0.4 - 0.57)
                dy = max(0, abs(y - q["cy"]) - q["ry"] - 0.4)
                checks.append((math.hypot(dx, dy) - r, f"ring {k}"))
        for b in bridges:
            for p, q2 in zip(b["points"], b["points"][1:]):
                if abs(p[0] - x) < r + 3 and abs(p[1] - y) < r + 3:
                    checks.append((seg_dist(x, y, p[0], p[1], q2[0], q2[1])[0] - 0.57 - r, f"bridge {b['id']}"))
        for f, _ in fillets:
            if math.hypot(f["cx"] - x, f["cy"] - y) < r + 3:
                checks.append((min(math.hypot(px - x, py - y) for px, py in arc(f)) - 0.13 - r, "fillet"))
        if s["district"] != "reef":
            checks.append((gap(x, y) - r, "lake"))
            checks.append((seg_dist(x, y, pier["x0"], pier["y0"], pier["x1"], pier["y1"])[0] - 0.25 - r, "pier"))
        for o in stages:
            if o is not s:
                checks.append((math.hypot(x - o["x"], y - o["y"]) - r - o["r"], f"stage {o['district']}"))
        low = min(checks)
        if low[0] < worst_s:
            worst_s, why_s = low[0], f"{s['district']} vs {low[1]}"
    gate("stages: 12, each clear by 0.5", len(stages) == 12 and len({s["district"] for s in stages}) == 12 and worst_s >= 0.5 - 1e-6,
         f"{len(stages)} stages, min clearance {worst_s:.3f} ({why_s})")

    # 10 and 11. Venue terraces and furniture never overlap a bridge landing, fillet, pier, link or the water.
    obst = Grid(2.0)
    for b in bridges:
        for p, q2 in zip(b["points"], b["points"][1:]):
            obst.add((p[0], p[1], q2[0], q2[1], 0.57), min(p[0], q2[0]) - 1, min(p[1], q2[1]) - 1, max(p[0], q2[0]) + 1, max(p[1], q2[1]) + 1)
    for f, _ in fillets:
        pts = arc(f)
        for p, q2 in zip(pts, pts[1:]):
            obst.add((p[0], p[1], q2[0], q2[1], 0.13), min(p[0], q2[0]) - 1, min(p[1], q2[1]) - 1, max(p[0], q2[0]) + 1, max(p[1], q2[1]) + 1)
    obst.add((pier["x0"], pier["y0"], pier["x1"], pier["y1"], 0.25), min(pier["x0"], pier["x1"]) - 1, min(pier["y0"], pier["y1"]) - 1,
             max(pier["x0"], pier["x1"]) + 1, max(pier["y0"], pier["y1"]) + 1)
    for st in design.get("streets", []):
        for p, q2 in zip(st["points"], st["points"][1:]):
            obst.add((p[0], p[1], q2[0], q2[1], st["width"] / 2 + 0.13), min(p[0], q2[0]) - 1, min(p[1], q2[1]) - 1,
                     max(p[0], q2[0]) + 1, max(p[1], q2[1]) + 1)

    def hit(x, y, r):
        for ax, ay, bx, by, half in obst.near(x, y):
            if seg_dist(x, y, ax, ay, bx, by)[0] < half + r:
                return True
        on_island = math.hypot(x - isl["x"], y - isl["y"]) <= isl["r"] - r
        return lower(x, y) < r + 0.5 and gap(x, y) < r and not on_island

    v_hits = 0
    for v in design["venues"]:
        if not v["terrace"]:
            continue
        nx, ny = v["face"]
        for a in (0.1, v["terrace"] * 0.5, v["terrace"]):
            for bb in (-0.35, 0, 0.35):
                v_hits += hit(v["x"] + nx * a - ny * bb * v["length"], v["y"] + ny * a + nx * bb * v["length"], 0.0)
    f_hits = sum(hit(it["x"], it["y"], FURNITURE_R.get(it["kind"], 0.1)) for it in design["furniture"] if it["kind"] != "manhole")
    gate("venues: no terrace on a bridge landing, fillet, pier, link or the lake", v_hits == 0,
         f"{v_hits} terrace samples hit, {sum(1 for v in design['venues'] if v['terrace'])} terraces")
    gate("furniture: no item on a bridge landing, fillet, pier, link or the lake", f_hits == 0,
         f"{f_hits} of {sum(1 for it in design['furniture'] if it['kind'] != 'manhole')} items hit")

    # 11b. The Archive east rim road (its own stretch, paved band and sidewalks, 0.57 from the centreline)
    # and the rim links (0.40): no stage deck overlaps them (a neighbour's deck keeps 0.5), no venue terrace
    # sample and no free-standing furniture item stands on them. Manholes are decals on the road (C4.1).
    rim_segs = []
    for i, r in enumerate(routes):
        if r.get("kind") == "rim":
            pts = W.route_pts[i]
            rim_segs += [(a[0], a[1], b2[0], b2[1], W.route_half(i) + SIDEWALK) for a, b2 in zip(pts, pts[1:])]
    for st in design.get("streets", []):
        rim_segs += [(a[0], a[1], b2[0], b2[1], st["width"] / 2 + SIDEWALK) for a, b2 in zip(st["points"], st["points"][1:])]
    rim_grid = Grid(2.0)
    for sg in rim_segs:
        rim_grid.add(sg, min(sg[0], sg[2]) - 1, min(sg[1], sg[3]) - 1, max(sg[0], sg[2]) + 1, max(sg[1], sg[3]) + 1)
    stage_rim, why_rim = 9.0, ""
    for s in stages:
        need = 0.0 if s["district"] == "episodic" else 0.5
        for ax, ay, bx, by, half in rim_segs:
            g_ = seg_dist(s["x"], s["y"], ax, ay, bx, by)[0] - half - s["r"] - need
            if g_ < stage_rim:
                stage_rim, why_rim = g_, s["district"]

    def on_rim(x, y, r):
        return any(seg_dist(x, y, ax, ay, bx, by)[0] < half + r for ax, ay, bx, by, half in rim_grid.near(x, y))
    rv_hits = 0
    for v in design["venues"]:
        if v["terrace"]:
            nx, ny = v["face"]
            for a in (0.1, v["terrace"] * 0.5, v["terrace"]):
                for bb in (-0.35, 0, 0.35):
                    rv_hits += on_rim(v["x"] + nx * a - ny * bb * v["length"], v["y"] + ny * a + nx * bb * v["length"], 0.0)
    rf_hits = sum(on_rim(it["x"], it["y"], FURNITURE_R.get(it["kind"], 0.1)) for it in design["furniture"]
                  if it["kind"] != "manhole")
    gate("rim clearance: no stage deck, venue terrace or furniture item on the rim road or a link",
         bool(rim_segs) and stage_rim >= -1e-6 and rv_hits == 0 and rf_hits == 0,
         f"closest stage margin {stage_rim:+.3f} ({why_rim}; own district 0, others 0.5), "
         f"{rv_hits} terrace samples and {rf_hits} furniture items on the rim road or a link")

    # 11c. The rest of C4.1 (V4 fix): every stage deck, venue terrace sample and furniture item (manholes are
    # road decals) stays off every street's carriageway and both walking lanes (route half width + 0.11 from
    # the centreline: the lane 0.04 outside the kerb plus a walker's 0.07; rings, avenues, the rim road's own
    # stretch, the rim links and the bridges); free-standing things (stage decks, carts, kiosks, bins, bus
    # stops) clear every building footprint (0.57 overhang) by 0.2; a terrace sample stands on no footprint
    # but its host's (a terrace set, the venue's tables, chairs and crates, belongs to its venue); and nothing
    # overlaps: stage and stage, stage and item (a cart on its own district's deck, as the viewer places it,
    # excepted), item and item (one venue's terrace set excepted), terrace sample and stage.
    band = Grid(2.0)
    for i, pts in enumerate(W.route_pts):
        closed = not routes[i].get("shared")
        ring = pts + ([pts[0]] if closed else [])
        for a, b2 in zip(ring, ring[1:]):
            band.add((a[0], a[1], b2[0], b2[1], W.route_half(i) + 0.11, f"route {i}"),
                     min(a[0], b2[0]) - 3, min(a[1], b2[1]) - 3, max(a[0], b2[0]) + 3, max(a[1], b2[1]) + 3)
    for k, st in enumerate(design.get("streets", [])):
        for a, b2 in zip(st["points"], st["points"][1:]):
            band.add((a[0], a[1], b2[0], b2[1], st["width"] / 2 + 0.11, f"link {k}"),
                     min(a[0], b2[0]) - 3, min(a[1], b2[1]) - 3, max(a[0], b2[0]) + 3, max(a[1], b2[1]) + 3)
    for b in bridges:
        for p_, q2 in zip(b["points"], b["points"][1:]):
            band.add((p_[0], p_[1], q2[0], q2[1], b["width"] / 2 + 0.11, f"bridge {b['id']}"),
                     min(p_[0], q2[0]) - 3, min(p_[1], q2[1]) - 3, max(p_[0], q2[0]) + 3, max(p_[1], q2[1]) + 3)

    def lane_gap(x, y, r):
        best, who = math.inf, ""
        for ax, ay, bx, by, half, name in band.near(x, y):
            d_ = seg_dist(x, y, ax, ay, bx, by)[0] - half - r
            if d_ < best:
                best, who = d_, name
        return best, who

    feet = Grid(2.0)
    for key, f in design["buildings"].items():
        bx, by = layout["pos"][key]
        hw, hd = f["w"] * 0.57, f["d"] * 0.57
        feet.add((key, bx, by, hw, hd), bx - hw - 3, by - hd - 3, bx + hw + 3, by + hd + 3)

    def foot_gap(x, y, skip=None):
        best = math.inf
        for key, bx, by, hw, hd in feet.near(x, y):
            if key != skip:
                best = min(best, math.hypot(max(0.0, abs(x - bx) - hw), max(0.0, abs(y - by) - hd)))
        return best

    c41 = []
    for s_ in stages:
        lg, who = lane_gap(s_["x"], s_["y"], s_["r"])
        if lg < -1e-6:
            c41.append(f"{s_['district']} stage on {who} ({lg:+.3f})")
        fg = foot_gap(s_["x"], s_["y"]) - s_["r"]
        if fg < 0.2 - 1e-6:
            c41.append(f"{s_['district']} stage {fg:.3f} from a footprint")
    for i, a in enumerate(stages):
        for b in stages[i + 1:]:
            if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < a["r"] + b["r"] - 1e-6:
                c41.append(f"stages {a['district']} and {b['district']} overlap")
    t_samples = 0
    for vi, v in enumerate(design["venues"]):
        if not v["terrace"]:
            continue
        nx, ny = v["face"]
        for a in (0.1, v["terrace"] * 0.5, v["terrace"]):
            for bb in (-0.35, 0, 0.35):
                x, y = v["x"] + nx * a - ny * bb * v["length"], v["y"] + ny * a + nx * bb * v["length"]
                t_samples += 1
                lg, who = lane_gap(x, y, 0.0)
                if lg < -1e-6:
                    c41.append(f"venue {vi} terrace on {who} ({lg:+.3f})")
                if foot_gap(x, y, str(v["host"])) <= 0:
                    c41.append(f"venue {vi} terrace on a footprint")
                for s_ in stages:
                    if math.hypot(x - s_["x"], y - s_["y"]) < s_["r"]:
                        c41.append(f"venue {vi} terrace on the {s_['district']} stage")
    items = [(i, it) for i, it in enumerate(design["furniture"]) if it["kind"] != "manhole"]
    on_stage = {i: next((s_ for s_ in stages if it["kind"] == "cart" and s_["district"] == it["district"] and
                         math.hypot(it["x"] - s_["x"], it["y"] - s_["y"]) < s_["r"] + 0.05), None) for i, it in items}
    for i, it in items:
        r = FURNITURE_R.get(it["kind"], 0.1)
        lg, who = lane_gap(it["x"], it["y"], r)
        if lg < -1e-6:
            c41.append(f"{it['kind']} {i} on {who} ({lg:+.3f})")
        if it.get("venue", -1) < 0:
            fg = foot_gap(it["x"], it["y"]) - r
            if fg < 0.2 - 1e-6:
                c41.append(f"{it['kind']} {i} {fg:.3f} from a footprint")
        for s_ in stages:
            if on_stage[i] is not s_ and math.hypot(it["x"] - s_["x"], it["y"] - s_["y"]) < s_["r"] + r - 1e-6:
                c41.append(f"{it['kind']} {i} on the {s_['district']} stage")
    pair_grid = Grid(1.0)
    for i, it in items:
        pair_grid.add((i, it), it["x"] - 0.4, it["y"] - 0.4, it["x"] + 0.4, it["y"] + 0.4)
    for i, a in items:
        ra = FURNITURE_R.get(a["kind"], 0.1)
        for j, b in pair_grid.near(a["x"], a["y"]):
            if j <= i or (a.get("venue", -1) >= 0 and a.get("venue") == b.get("venue")):
                continue
            if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < ra + FURNITURE_R.get(b["kind"], 0.1) - 1e-6:
                c41.append(f"{a['kind']} {i} and {b['kind']} {j} overlap")
    gate("C4.1: stages, terraces and furniture clear roads, walking lanes, footprints and each other", not c41,
         f"{len(c41)} overlaps" + (f", first: {c41[0]}" if c41 else
                                   f" ({len(stages)} stages, {t_samples} terrace samples, {len(items)} items)"))

    # 12. Published measurements are measurements: every clearance field and overpass list matches
    # what this checker measures on the published geometry (later gates read these fields).
    lies = []
    rebuilt = arclen(tour["points"], closed=True)[-1]
    if abs(rebuilt - tour["length"]) > 0.01:
        lies.append(f"tour length {tour['length']} vs the rebuilt polyline {rebuilt:.3f}")
    if abs(lake["ringClearance"] - ring_gap) > 0.02:
        lies.append(f"lake.ringClearance {lake['ringClearance']} vs {ring_gap:.3f}")
    if abs(lake["bridgeClearance"] - bridge_gap) > 0.02:
        lies.append(f"lake.bridgeClearance {lake['bridgeClearance']} vs {bridge_gap:.3f}")
    for s in design.get("streets", []):
        if abs(s["clearance"] - measured[s["name"]]) > 0.01:
            lies.append(f"{s['name']} clearance {s['clearance']} vs {measured[s['name']]:.3f}")
    for i, r in enumerate(routes):
        if r.get("kind") == "rim":
            if abs(r["clearanceOwn"] - measured[r["name"]]) > 0.01:
                lies.append(f"{r['name']} clearanceOwn {r['clearanceOwn']} vs {measured[r['name']]:.3f}")
            whole = min(W.foot_exact(p[0], p[1]) for p in r["points"])
            if abs(r["clearance"] - whole) > 0.01:
                lies.append(f"{r['name']} clearance {r['clearance']} vs {whole:.3f}")
    over_pub = set()
    for b in bridges:
        if abs(b["clearance"] - exact_clear[b["id"]]) > 0.02:
            lies.append(f"bridge {b['id']} clearance {b['clearance']} vs {exact_clear[b['id']]:.3f}")
        for o in b["overpasses"]:
            over_pub.add((b["id"], o["kind"], o["index"]))
            got = worst["over"].get((b["id"], (o["kind"], o["index"])))
            if got is None or abs(got[0] - o["clearance"]) > 0.03 or o.get("overlap") != any(
                    st[0] == b["id"] and st[1] == (o["kind"], o["index"]) and st[2] != "fillet" for st in worst["stack"]):
                lies.append(f"bridge {b['id']} overpass {o['kind']} {o['index']} published {o} vs measured {got}")
    # Every overpass over a ring or link is published on its bridge; a bridge-over-bridge crossing is
    # published on at least one of the two.
    for (bid, o) in worst["over"]:
        if o[0] != "bridge" and (bid, o[0], o[1]) not in over_pub:
            lies.append(f"bridge {bid} overpass over {o} measured but not published")
        if o[0] == "bridge" and (bid, "bridge", o[1]) not in over_pub and (o[1], "bridge", bid) not in over_pub:
            lies.append(f"bridges {bid} and {o[1]} cross but neither publishes it")
    gate("published clearances and overpasses match the measurements", not lies,
         f"{len(lies)} mismatches" + (f", first: {lies[0]}" if lies else
                                      f"; lake rings {ring_gap:.3f}, lake bridges {bridge_gap:.3f}, "
                                      f"{len(design.get('streets', []))} links, rim road, 14 bridges, "
                                      f"{len(over_pub)} overpasses"))

    if not quiet:
        width = max(len(k) for k in res)
        for k, (ok, m) in res.items():
            print(f"{'PASS' if ok else 'FAIL'}  {k:<{width}}  {m}")
    return res


# ------------------------------------------------------------------ positive control
def control(page, layout):
    """For every gate, break the design in a throwaway copy and show that the gate goes red. Most breaks
    edit the rebuilt design; the page breaks edit the page data itself and are rebuilt afterwards, so a
    wrong rebuild input (a tour start, a fillet angle) is shown to turn gates red too."""
    D = layout["districts"]
    design = expand(page)
    names = list(run(design, layout, quiet=True))

    def g(prefix):
        hits = [n for n in names if n.startswith(prefix)]
        assert len(hits) == 1, prefix
        return hits[0]

    def mid(d, k):
        b = d["bridges"][k]
        return b, len(b["points"]) // 2

    def box_of(d, x, y):
        key = min(d["buildings"], key=lambda k: math.dist(layout["pos"][k], (x, y)))
        f = d["buildings"][key]
        bx, by = layout["pos"][key]
        return bx, by, f["w"] * 0.57, f["d"] * 0.57

    def count_break(d):
        gone = d["bridges"].pop()
        d["graph"]["edges"] = [e for e in d["graph"]["edges"] if e.get("bridge") != gone["id"]]
        return [g("bridges: 14")]

    def graph_break(d):
        gr = d["graph"]
        dome = {e["id"] for e in gr["edges"] if e["kind"] == "bridge" and "onebrain" in (d["bridges"][e["bridge"]]["from"], d["bridges"][e["bridge"]]["to"])}
        gr["edges"] = [e for e in gr["edges"] if e["id"] not in dome]
        return [g("graph: one connected"), g("graph: every district")]

    def turn_break(d):
        node = next(n for n in d["graph"]["nodes"] if n["kind"] == "tee")
        first = next(m[4] for m in node["moves"] if m[4] >= 0)
        for m in node["moves"]:
            if m[4] >= 0:
                m[4] = first
        return [g("graph: every tee turns")]

    def side_break(d):
        d["graph"]["turns"][5]["ringSide"] *= -1
        return [g("graph: every tee turns")]

    def move_break(d):
        gr = d["graph"]
        dome_edge = next(e for e in gr["edges"] if e["kind"] == "bridge" and "onebrain" in (e["from"], e["to"]))
        dome_end = 0 if gr["nodes"][dome_edge["a"]]["district"] == "onebrain" else 1
        node = gr["nodes"][dome_edge["a"] if dome_end == 0 else dome_edge["b"]]
        # Arriving on the Dome bridge, nothing may turn onto the Dome ring any more.
        node["moves"] = [m for m in node["moves"] if not (m[0] == dome_edge["id"] and m[1] == dome_end)]
        return [g("graph: every drivable state")]

    def grade_break(d):
        b, m = mid(d, 7)
        for p in b["points"][m - 2:m + 3]:
            p[2] += 0.6
        return [g("grade <= 12"), g("deck vertical curvature")]

    def bend_break(d):
        b, m = mid(d, 8)
        b["points"][m][2] += 0.012
        return [g("deck vertical curvature")]

    def foot_break(d):
        b, m = mid(d, 12)
        x, y = b["points"][m][:2]
        bx, by, _, _ = box_of(d, x, y)
        for p in b["points"][m - 1:m + 2]:
            p[0], p[1] = bx, by
        return [g("deck centreline"), g("deck point +0.64"), g("chase camera +0.32")]

    def lane_break(d):
        # Three deck points run north-south 0.30 east of a Downtown building: the centreline passes
        # the 0.20 street check, the sidewalk lane at 0.48 does not.
        b, m = mid(d, 12)
        x, y = b["points"][m][:2]
        bx, by, hw, hd = box_of(d, x, y)
        z = D["working"]["z"] + 0.035
        for j, p in enumerate(b["points"][m - 1:m + 2]):
            p[0], p[1], p[2] = bx + hw + 0.30, by - 0.1 + 0.1 * j, z
        return [g("both walking lanes")]

    def plateau_break(d):
        b, m = mid(d, 7)
        p = D["jhon"]
        for q in b["points"][m - 1:m + 2]:
            q[0], q[1] = p["cx"], p["cy"]
        return [g("no deck over a plateau")]

    def separation_break(d):
        b, m = mid(d, 11)
        ring = d["routes"][next(i for i, r in enumerate(d["routes"]) if r["district"] == "working")]
        x, y = ring["points"][len(ring["points"]) // 4]
        for p in b["points"][m - 1:m + 2]:
            p[0], p[1], p[2] = x, y, ring["z"] + 0.2
        return [g("0.5 horizontal")]

    def stack_break(d):
        b, m = mid(d, 12)
        ring = d["routes"][next(i for i, r in enumerate(d["routes"]) if r["district"] == "prasma")]
        k = len(ring["points"]) // 8
        for j, p in enumerate(b["points"][m - 1:m + 2]):
            x, y = ring["points"][k + j]
            p[0], p[1], p[2] = x, y, ring["z"] + 0.7
        return [g("one walkable height")]

    def corner_break(d):
        # Slide one junction corner of the Downtown to Reef bridge onto the Prasma Campus ring.
        ring = d["routes"][next(i for i, r in enumerate(d["routes"]) if r["district"] == "prasma")]
        f = d["bridges"][12]["ends"][1]["fillets"][0]
        mx = f["cx"] + f["r"] * math.cos(math.radians((f["a0"] + f["a1"]) / 2))
        my = f["cy"] + f["r"] * math.sin(math.radians((f["a0"] + f["a1"]) / 2))
        x, y = min(ring["points"], key=lambda q: math.dist(q, (mx, my)))
        f["cx"] += x - mx
        f["cy"] += y - my
        return [g("one walkable height")]

    def camdeck_break(d):
        b, m = mid(d, 12)
        o, n = mid(d, 13)
        for j, p in enumerate(b["points"][m - 1:m + 2]):
            q = o["points"][n - 1 + j]
            p[0], p[1], p[2] = q[0], q[1], q[2] - 0.3
        return [g("chase camera under no overpass")]

    def junction_break(d):
        d["bridges"][5]["points"][0][2] += 0.1
        return [g("junction continuity")]

    def fillet_break(d):
        d["bridges"][2]["ends"][0]["fillets"][0]["r"] = 0.6
        return [g("fillet radius")]

    def street_break(d):
        rim = next(r for r in d["routes"] if r.get("kind") == "rim")
        bx, by, _, _ = box_of(d, rim["points"][40][0], rim["points"][40][1])
        for p in rim["points"][38:43]:
            p[0], p[1] = bx, by
        return [g("rim road")]

    def ccw_break(d):
        rim = next(r for r in d["routes"] if r.get("kind") == "rim")
        rim["points"].reverse()
        return [g("routes run counterclockwise")]

    def tour_gap_break(d):
        del d["tour"]["points"][100:120]
        return [g("tour: closed walk")]

    def tour_break(d):
        d["tour"]["entries"] = [e for e in d["tour"]["entries"] if e["district"] != "inbox"]
        return [g("tour: visits all")]

    def entry_break(d):
        d["tour"]["entries"][3]["s"] += 3.0
        return [g("tour: entries in order")]

    def loop_break(d):
        # Cut the Dome loop: drop every tour point on the far half of the Dome ring.
        t, p = d["tour"], D["onebrain"]
        i = next(i for i, e in enumerate(t["entries"]) if e["district"] == "onebrain")
        span = t["spans"][i]
        leg = next(l for l in t["legs"] if l["to"] == "onebrain")
        b = d["bridges"][leg["bridge"]]
        e = next(e for e in b["ends"] if e["district"] == "onebrain")
        home = math.atan2(e["y"] - p["cy"], e["x"] - p["cx"])
        cum = arclen(t["points"], closed=False)
        keep = []
        for pt, s in zip(t["points"], cum):
            far = abs((math.atan2(pt[1] - p["cy"], pt[0] - p["cx"]) - home + math.pi) % math.tau - math.pi) > math.pi / 2
            if span["from"] < s < span["to"] and far and math.hypot(pt[0] - p["cx"], pt[1] - p["cy"]) < p["rx"] + 2:
                continue
            keep.append(pt)
        t["points"] = keep
        return [g("tour: leaves")]

    def offroad_break(d):
        for p in d["tour"]["points"][300:310]:
            p[0] += 1.0
        return [g("tour: every sample on a carriageway")]

    def tourcam_break(d):
        pts = d["tour"]["points"]
        bx, by, _, _ = box_of(d, pts[400][0], pts[400][1])
        for p in pts[399:402]:
            p[0], p[1] = bx, by
        return [g("tour: chase camera")]

    def shore_break(d):
        lk, reef = d["lake"][0], D["reef"]
        ux, uy = lk["cx"] - reef["cx"], lk["cy"] - reef["cy"]
        n = math.hypot(ux, uy)
        lk["cx"] += 0.5 * ux / n
        lk["cy"] += 0.5 * uy / n
        return [g("lake: near shore")]

    def lake_break(d):
        lk = d["lake"][0]
        ring = d["routes"][next(i for i, r in enumerate(d["routes"]) if r["district"] == "prasma")]
        lk["cx"], lk["cy"] = ring["points"][0]
        return [g("lake: clears every other ring")]

    def lakebridge_break(d):
        lk = d["lake"][0]
        b, m = mid(d, 13)
        for p in b["points"][m - 1:m + 2]:
            p[0], p[1] = lk["cx"], lk["cy"]
        return [g("lake: clears every bridge")]

    def pier_break(d):
        pr = d["lake"][0]["pier"]
        pr["x1"], pr["y1"] = (pr["x0"] + pr["x1"]) / 2, (pr["y0"] + pr["y1"]) / 2
        return [g("pier 0.5 x 5")]

    def booth_break(d):
        s = next(s for s in d["stages"] if s["district"] == "reef")
        s["angle"] = (s["angle"] + math.pi) % math.tau
        return [g("Reef island stage")]

    def stage_break(d):
        s = next(s for s in d["stages"] if s["district"] == "working")
        b = d["bridges"][12]
        s["x"], s["y"] = b["points"][len(b["points"]) // 2][:2]
        return [g("stages: 12")]

    def venue_break(d):
        v = next(v for v in d["venues"] if v["terrace"])
        b = d["bridges"][0]
        v["x"], v["y"] = b["points"][len(b["points"]) // 2][:2]
        return [g("venues:")]

    def furniture_break(d):
        it = next(it for it in d["furniture"] if it["kind"] == "bin")
        b = d["bridges"][0]
        it["x"], it["y"] = b["points"][len(b["points"]) // 2][:2]
        return [g("furniture:")]

    def truth_break(d):
        d["lake"][0]["ringClearance"] = 4.524
        return [g("published clearances")]

    def truth_break2(d):
        d["streets"][0]["clearance"] = 6.0
        return [g("published clearances")]

    def rim_point(d, frac):
        rim = next(r for r in d["routes"] if r.get("kind") == "rim")
        own = [p for p, c in zip(rim["points"], arclen(rim["points"])) if c <= rim["shared"][0]["from"]]
        return own[int(len(own) * frac)]

    def rim_stage_break(d):
        s = next(s for s in d["stages"] if s["district"] == "episodic")
        s["x"], s["y"] = rim_point(d, 0.5)
        return [g("rim clearance")]

    def rim_terrace_break(d):
        v = next(v for v in d["venues"] if v["terrace"])
        v["x"], v["y"] = rim_point(d, 0.3)
        return [g("rim clearance")]

    def rim_furniture_break(d):
        it = next(it for it in d["furniture"] if it["kind"] == "kiosk")
        it["x"], it["y"] = rim_point(d, 0.7)
        return [g("rim clearance")]

    # The rest of C4.1: a kiosk on the Downtown ring (the review's known-bad input), a bin stacked on a street
    # cart, a free bin against a building, a terrace run out into its road, a stage pushed into its ring.
    def c41_lane_break(d):
        it = next(it for it in d["furniture"] if it["kind"] == "kiosk")
        ring = next(r for r in d["routes"] if r["district"] == "working")
        it["x"], it["y"] = ring["points"][len(ring["points"]) // 3]
        return [g("C4.1:")]

    def c41_pair_break(d):
        cart = next(it for it in d["furniture"] if it["kind"] == "cart" and it["venue"] < 0 and
                    not any(s_["district"] == it["district"] and math.hypot(it["x"] - s_["x"], it["y"] - s_["y"]) < s_["r"] + 0.05
                            for s_ in d["stages"]))
        it = next(it for it in d["furniture"] if it["kind"] == "bin")
        it["x"], it["y"] = cart["x"] + 0.05, cart["y"]
        return [g("C4.1:")]

    def c41_foot_break(d):
        it = next(it for it in d["furniture"] if it["kind"] == "bin")
        bx, by, hw, _ = box_of(d, it["x"], it["y"])
        it["x"], it["y"] = bx + hw + 0.1, by
        return [g("C4.1:")]

    def c41_terrace_break(d):
        v = next(v for v in d["venues"] if v["terrace"])
        v["terrace"] = v["gap"] + 0.4
        return [g("C4.1:")]

    def c41_stage_break(d):
        s_ = next(s_ for s_ in d["stages"] if s_["district"] == "working")
        p_ = D["working"]
        ux, uy = s_["x"] - p_["cx"], s_["y"] - p_["cy"]
        n_ = math.hypot(ux, uy)
        s_["x"] -= 1.2 * ux / n_
        s_["y"] -= 1.2 * uy / n_
        return [g("C4.1:")]

    # Page breaks: the page data is edited, then rebuilt.
    def page_s0_break(p):
        p["tour"]["s0"] += 3.0
        return [g("tour: entries in order")]

    def page_fillet_break(p):
        f = p["bridges"][9]["ends"][0]["fillets"][0]
        f["a1"] += 25.0
        return [g("graph: every tee turns")]

    def page_trim_break(p):
        t = next(t for t in p["graph"]["turns"] if t["bridge"] == 7)
        t["trimRing"] += 0.8
        return [g("graph: every tee turns")]

    def page_count_break(p):
        p["tour"]["count"] = p["tour"]["count"] // 3
        return [g("tour: closed walk")]

    breaks = (count_break, graph_break, turn_break, side_break, move_break, grade_break, bend_break, foot_break,
              lane_break, plateau_break, separation_break, stack_break, corner_break, camdeck_break, junction_break, fillet_break,
              street_break, ccw_break, tour_gap_break, tour_break, entry_break, loop_break, offroad_break,
              tourcam_break, shore_break, lake_break, lakebridge_break, pier_break, booth_break, stage_break,
              venue_break, furniture_break, truth_break, truth_break2, rim_stage_break, rim_terrace_break,
              rim_furniture_break, c41_lane_break, c41_pair_break, c41_foot_break, c41_terrace_break, c41_stage_break,
              page_s0_break, page_fillet_break, page_trim_break, page_count_break)
    rows, all_red, covered = [], True, set()
    for fn in breaks:
        if fn.__name__.startswith("page_"):
            p = copy.deepcopy(page)
            targets = fn(p)
            d = expand(p)
        else:
            d = copy.deepcopy(design)
            targets = fn(d)
        try:
            res = run(d, layout, quiet=True)
            for target in targets:
                red = not res[target][0]
                covered.add(target) if red else None
                all_red &= red
                rows.append((fn.__name__, target, "RED" if red else "stayed green", res[target][1]))
        except Exception as err:  # a crash is not a red gate
            all_red = False
            rows.append((fn.__name__, ",".join(targets), "crashed", repr(err)))
    for name, target, state, m in rows:
        print(f"{state:12s} {name:17s} -> {target}: {m[:160]}")
    uncovered = [n for n in names if n not in covered]
    print(f"{len(covered)} of {len(names)} gates shown red by a control" + (f"; never red: {uncovered}" if uncovered else ""))
    return all_red and not uncovered


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("design", nargs="?", default=str(ROOT / "data" / "city-design.json"))
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--json", help="also write the gate table to this path")
    args = ap.parse_args()
    page = json.loads(Path(args.design).read_text(encoding="utf-8"))
    layout = json.loads((ROOT / "data" / "layout.json").read_text(encoding="utf-8"))
    if args.control:
        ok = control(page, layout)
        print("positive control:", "every gate went red on its broken input" if ok else "SOME GATE NEVER WENT RED")
        return 0 if ok else 1
    res = run(expand(page), layout)
    if args.json:
        Path(args.json).write_text(json.dumps({k: {"pass": ok, "measured": m} for k, (ok, m) in res.items()}, indent=1),
                                   encoding="utf-8")
    failed = [k for k, (ok, _) in res.items() if not ok]
    print(f"{len(res) - len(failed)} of {len(res)} gates pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
