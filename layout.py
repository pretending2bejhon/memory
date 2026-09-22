"""layout.py - compute the city plan from data/vault-city.json (standard library only).

Writes data/layout.json:
  spacing: building pitch in world units
  districts: name -> {cx, cy, shape: disc|rect, rx, ry, z (plateau height), n}
  pos: id -> [x, y] world position of the building centre
  bounds: [minx, miny, maxx, maxy]

Episodic is laid out as streets by week (buildings on both sides of a street, one
street row per chunk of a week). Every other district is a force-directed layout
(Fruchterman-Reingold on the intra-district edges) followed by overlap removal.
"""
import json, math, os, random, collections

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "vault-city.json")
OUT = os.path.join(HERE, "data", "layout.json")

S = 1.25            # building pitch
SIDE = 26           # buildings per side of an episodic street
STREET_PITCH = 2.4  # distance between street centre lines, in S units
PLATEAU_Z = {
    "core": 2.4, "semantic": 1.0, "procedural": 1.0, "working": 1.0, "prospective": 1.0,
    "inbox": 1.0, "jhon": 0.75, "episodic": 0.35,
}
VENTURE_Z = 0.55


def fr_layout(ids, edges, seed=7, iters=160):
    """Fruchterman-Reingold in a unit-ish square. Returns {id: (x, y)}."""
    n = len(ids)
    rnd = random.Random(seed)
    if n == 1:
        return {ids[0]: (0.0, 0.0)}
    idx = {v: i for i, v in enumerate(ids)}
    W = math.sqrt(n) * 1.0
    pos = [[rnd.uniform(-W, W), rnd.uniform(-W, W)] for _ in ids]
    k = 1.0
    t = W * 0.5
    adj = [[] for _ in ids]
    for a, b in edges:
        if a in idx and b in idx and a != b:
            adj[idx[a]].append(idx[b])
            adj[idx[b]].append(idx[a])
    for it in range(iters):
        disp = [[0.0, 0.0] for _ in ids]
        for i in range(n):
            xi, yi = pos[i]
            dx_acc = dy_acc = 0.0
            for j in range(i + 1, n):
                dx = xi - pos[j][0]; dy = yi - pos[j][1]
                d2 = dx * dx + dy * dy
                if d2 < 1e-6:
                    dx, dy, d2 = rnd.uniform(-0.01, 0.01), rnd.uniform(-0.01, 0.01), 1e-4
                f = k * k / d2          # repulsion / distance, applied to unit vector
                fx, fy = dx * f, dy * f
                dx_acc += fx; dy_acc += fy
                disp[j][0] -= fx; disp[j][1] -= fy
            disp[i][0] += dx_acc; disp[i][1] += dy_acc
        for i in range(n):
            xi, yi = pos[i]
            for j in adj[i]:
                dx = xi - pos[j][0]; dy = yi - pos[j][1]
                d = math.hypot(dx, dy) + 1e-9
                f = d / k * 0.5         # attraction (each edge visited twice)
                disp[i][0] -= dx / d * f * d
                disp[i][1] -= dy / d * f * d
            # gravity toward centre
            disp[i][0] -= xi * 0.08 * n ** 0.5 / 10
            disp[i][1] -= yi * 0.08 * n ** 0.5 / 10
        for i in range(n):
            dx, dy = disp[i]
            d = math.hypot(dx, dy) + 1e-9
            m = min(d, t)
            pos[i][0] += dx / d * m
            pos[i][1] += dy / d * m
        t = max(0.02, t * 0.96)
    return {v: (pos[i][0], pos[i][1]) for v, i in idx.items()}


def remove_overlaps(pts, min_d, iters=60):
    keys = list(pts)
    p = {k: [pts[k][0], pts[k][1]] for k in keys}
    for _ in range(iters):
        moved = False
        for i in range(len(keys)):
            a = p[keys[i]]
            for j in range(i + 1, len(keys)):
                b = p[keys[j]]
                dx = b[0] - a[0]; dy = b[1] - a[1]
                d = math.hypot(dx, dy)
                if d < min_d:
                    if d < 1e-6:
                        dx, dy, d = 0.01, 0.0, 0.01
                    push = (min_d - d) * 0.5
                    ux, uy = dx / d, dy / d
                    a[0] -= ux * push; a[1] -= uy * push
                    b[0] += ux * push; b[1] += uy * push
                    moved = True
        if not moved:
            break
    return {k: (v[0], v[1]) for k, v in p.items()}


def scale_to_disc(pts, radius):
    if not pts:
        return pts
    cx = sum(v[0] for v in pts.values()) / len(pts)
    cy = sum(v[1] for v in pts.values()) / len(pts)
    r = max(math.hypot(v[0] - cx, v[1] - cy) for v in pts.values()) or 1.0
    s = radius / r
    return {k: ((v[0] - cx) * s, (v[1] - cy) * s) for k, v in pts.items()}


def episodic_streets(nodes):
    """Streets by week. Returns local positions and (w, h) of the block."""
    by_week = collections.defaultdict(list)
    for n in nodes:
        c = n["created"]
        w = 13 if c is None else max(0, min(12, c))
        by_week[w].append(n["id"])
    pos = {}
    y = 0.0
    width = 0.0
    street_rows = []
    for w in sorted(by_week):
        ids = sorted(by_week[w])
        chunks = [ids[i:i + 2 * SIDE] for i in range(0, len(ids), 2 * SIDE)]
        for chunk in chunks:
            n = len(chunk)
            per_side = (n + 1) // 2
            x0 = -(per_side - 1) * S / 2
            for k, nid in enumerate(chunk):
                side = k % 2
                col = k // 2
                x = x0 + col * S
                yy = y + (0.62 * S if side == 0 else -0.62 * S)
                pos[nid] = (x, yy)
            width = max(width, per_side * S)
            street_rows.append((y, w))
            y -= STREET_PITCH * S
    height = -y + STREET_PITCH * S
    # centre the block
    cy = (0.0 + (y + STREET_PITCH * S)) / 2
    pos = {k: (v[0], v[1] - cy) for k, v in pos.items()}
    rows = [(r - cy, w) for r, w in street_rows]
    return pos, width, height, rows


def circles_overlap(a, b, gap):
    return math.hypot(a[0] - b[0], a[1] - b[1]) < a[2] + b[2] + gap


def circle_rect_overlap(c, r, gap):
    # c: (x, y, rad); r: (cx, cy, hw, hh)
    dx = max(abs(c[0] - r[0]) - r[2], 0.0)
    dy = max(abs(c[1] - r[1]) - r[3], 0.0)
    return math.hypot(dx, dy) < c[2] + gap


def main():
    with open(DATA, encoding="utf-8") as fh:
        data = json.load(fh)
    nodes = data["nodes"]
    edges = [tuple(e) for e in data["edges"]]
    by_d = collections.defaultdict(list)
    for n in nodes:
        by_d[n["district"]].append(n)
    dist_of = {n["id"]: n["district"] for n in nodes}

    pos = {}
    districts = {}

    # episodic block
    epos, ew, eh, rows = episodic_streets(by_d["episodic"])
    districts["episodic"] = {"shape": "rect", "rx": eh / 2 + 0.3 * S, "ry": ew / 2 + 1.0 * S,
                             "z": PLATEAU_Z["episodic"], "n": len(by_d["episodic"]),
                             "streets": [[r, w] for r, w in rows]}
    local = {"episodic": epos}

    # force-directed districts
    for d, ns in by_d.items():
        if d == "episodic":
            continue
        ids = [n["id"] for n in ns]
        idset = set(ids)
        intra = [e for e in edges if e[0] in idset and e[1] in idset]
        lp = fr_layout(ids, intra, seed=sum(ord(ch) * (i + 1) for i, ch in enumerate(d)))
        radius = S * math.sqrt(len(ids)) * 0.70 + 0.3 * S
        lp = scale_to_disc(lp, radius)
        lp = remove_overlaps(lp, S * 0.95)
        lp = scale_to_disc(lp, max(radius, max(math.hypot(*v) for v in lp.values())))
        rmax = max(math.hypot(*v) for v in lp.values()) if len(ids) > 1 else 0.0
        local[d] = lp
        districts[d] = {"shape": "disc", "rx": rmax + 0.9 * S, "ry": rmax + 0.9 * S,
                        "z": PLATEAU_Z.get(d, VENTURE_Z), "n": len(ids)}

    # plateau placement: core at origin, episodic behind (+y), others packed in front/sides
    gap = 1.6 * S
    placed = {}
    placed["core"] = (0.0, 0.0)
    core_r = districts["core"]["rx"]
    order = sorted((d for d in districts if d not in ("core", "episodic")),
                   key=lambda d: -districts[d]["n"])
    # preferred angles (degrees) in the front half, alternating left/right
    prefs = [0, -45, 45, -90, 90, -20, 20, -70, 70, -120, 120, -150, 150]
    circles = [(0.0, 0.0, core_r)]
    for i, d in enumerate(order):
        r = districts[d]["rx"]
        best = None
        for ang in ([prefs[i % len(prefs)]] + [prefs[(i + k) % len(prefs)] for k in range(1, len(prefs))]):
            a = math.radians(ang)
            dist = core_r + r + gap
            for _ in range(200):
                cx, cy = math.cos(a) * dist, math.sin(a) * dist
                if not any(circles_overlap((cx, cy, r), c, gap) for c in circles):
                    break
                dist += 0.5 * S
            if best is None or dist < best[0]:
                best = (dist, cx, cy)
        placed[d] = (best[1], best[2])
        circles.append((best[1], best[2], r))
    # episodic rectangle on the left (-x), vertically centred on the cluster
    left = min(c[0] - c[2] for c in circles)
    ys = [c[1] for c in circles]
    ex, ey = left - gap - districts["episodic"]["rx"], (max(ys) + min(ys)) / 2
    placed["episodic"] = (ex, ey)

    for d, lp in local.items():
        cx, cy = placed[d]
        districts[d]["cx"], districts[d]["cy"] = cx, cy
        for nid, (x, y) in lp.items():
            if d == "episodic":
                x, y = y, x      # transpose: streets run along y, stacked along x
            pos[nid] = [round(cx + x, 3), round(cy + y, 3)]

    xs = [v[0] for v in pos.values()]; ys = [v[1] for v in pos.values()]
    bounds = [min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3]
    out = {"spacing": S, "districts": districts, "pos": {str(k): v for k, v in pos.items()},
           "bounds": bounds}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print("layout: %d positions, bounds %s" % (len(pos), [round(b, 1) for b in bounds]))
    for d in sorted(districts, key=lambda d: -districts[d]["n"]):
        i = districts[d]
        print("  %-12s n=%4d at (%6.1f,%6.1f) r=(%5.1f,%5.1f) z=%.2f" % (d, i["n"], i["cx"], i["cy"], i["rx"], i["ry"], i["z"]))


if __name__ == "__main__":
    main()
