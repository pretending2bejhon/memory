"""city.py - build and render vault-city in Blender (bpy only, no add-ons).

Usage (headless):
  blender -b --python city.py -- --mode iter --iter 1 --week 12
  modes: iter | final | timelapse | turntable | glb
"""
import bpy, json, math, os, sys, time, datetime
from mathutils import Vector, Matrix

T0 = time.time()
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from blender_design import geometry as detailed_geometry, environment as build_environment
DATA = os.path.join(HERE, "data", "vault-city.json")
LAYOUT = os.path.join(HERE, "data", "layout.json")
RENDERS = os.path.join(HERE, "renders")
os.makedirs(RENDERS, exist_ok=True)

# ---------------------------------------------------------------- arguments
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default):
    if name in argv:
        return argv[argv.index(name) + 1]
    return default
MODE = arg("--mode", "iter")
ITER = int(arg("--iter", "0"))
WEEK = int(arg("--week", "12"))
LAST_WEEK = 12
WEEK0 = datetime.date(2026, 6, 29)
EXPORT_DATE = datetime.date(2026, 9, 21)

# ---------------------------------------------------------------- palette (sRGB hex)
def hex_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)

def to_linear(c):
    out = []
    for v in c:
        out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return tuple(out)

def lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))

NIGHT = hex_rgb("#09131f")
DEEP = hex_rgb("#030913")
BASE = hex_rgb("#687c93")
SIGNAL = hex_rgb("#be95ff")
HIGHLIGHT = hex_rgb("#d7afff")
DIM1 = hex_rgb("#a9a1bf")
DIM2 = hex_rgb("#958ba9")
BONE = hex_rgb("#e8ddd0")
GRID = lerp(NIGHT, (68 / 255.0, 56 / 255.0, 79 / 255.0), 0.55)

def col4(c, a=1.0):
    l = to_linear(c)
    return (l[0], l[1], l[2], a)

# ---------------------------------------------------------------- data
with open(DATA, encoding="utf-8") as fh:
    data = json.load(fh)
with open(LAYOUT, encoding="utf-8") as fh:
    layout = json.load(fh)
NODES = {n["id"]: n for n in data["nodes"]}
EDGES = [tuple(e) for e in data["edges"]]
POS = {int(k): v for k, v in layout["pos"].items()}
DISTRICTS = layout["districts"]
S = layout["spacing"]
with open(os.path.join(HERE, "data", "city-design.json"), encoding="utf-8") as fh:
    DESIGN = json.load(fh)

def plateau_z(d):
    return DISTRICTS[d]["z"]

# ---------------------------------------------------------------- decay rules (see LOG.md)
def frame_date(w):
    return WEEK0 + datetime.timedelta(days=7 * w)

def appear_week(n):
    c = n["created"]
    return 0 if c is None else max(0, min(LAST_WEEK, c))

def light_state(n, w):
    """Returns (state, light) with state in absent|foundation|dark|lit and light in [0,1]."""
    if n["created"] is None:
        return "foundation", 0.0
    if appear_week(n) > w:
        return "absent", 0.0
    if n["status"] != "active":
        return "dark", 0.0
    last = n["created"]
    if n["updated"] is not None:
        last = max(last, n["updated"])
    touch = frame_date(last)
    if w >= LAST_WEEK and n["retrieval_count"] > 0:
        touch = max(touch, EXPORT_DATE)
    age = (frame_date(w) - touch).days
    if age <= 45:
        return "lit", 1.0
    if age >= 90:
        return "lit", 0.15
    return "lit", 1.0 - (age - 45) / 45.0 * 0.85

BODY_GAIN = 0.82

def body_color(n, state, light):
    if state == "foundation":
        c = lerp(NIGHT, BASE, 0.25)
    elif state == "dark":
        c = lerp(NIGHT, BASE, 0.30)
    else:
        c = lerp(NIGHT, BASE, 0.3 + 0.7 * light)
    return lerp(NIGHT, c, BODY_GAIN)

def light_color(n, state, light, body):
    if state != "lit":
        return None
    sig = hex_rgb(DESIGN["palette"].get(n["district"], "#be95ff"))
    glow = min(1.0, math.log2(1 + n["retrieval_count"]) / 5.0)
    full = lerp(sig, BONE, 0.12 * glow)
    t = (light - 0.15) / 0.85
    c = lerp(DIM2, full, max(0.0, t))
    return lerp(body, c, 0.3 + 0.7 * light)

# ---------------------------------------------------------------- footprints
def rect(w, d):
    return [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]

def hexagon(r):
    return [(r * math.cos(math.radians(60 * i + 30)), r * math.sin(math.radians(60 * i + 30))) for i in range(6)]

def building_shape(n, state):
    """Returns (polygon, height)."""
    f = DESIGN["buildings"][str(n["id"])]
    return rect(f["w"], f["d"]), f["h"]

def extrude_bevel(poly, h, bevel, inset, z0=0.0, profile=1):
    """Vertices/faces for a prism with a chamfered (profile=1) or rounded (profile>1) top."""
    n = len(poly)
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n
    verts = []
    rings = []
    def add_ring(ins, z):
        base = len(verts)
        for (x, y) in poly:
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy) or 1.0
            f = max(0.0, 1.0 - ins / d)
            verts.append((cx + dx * f, cy + dy * f, z))
        rings.append(base)
    add_ring(0.0, z0)
    if profile <= 1:
        add_ring(0.0, z0 + h - bevel)
        add_ring(inset, z0 + h)
    else:
        for k in range(profile + 1):
            a = math.pi / 2 * k / profile
            add_ring(inset * (1 - math.cos(a)), z0 + h - bevel + bevel * math.sin(a))
    faces = []
    for r in range(len(rings) - 1):
        a, b = rings[r], rings[r + 1]
        for i in range(n):
            j = (i + 1) % n
            faces.append((a + i, a + j, b + j, b + i))
    top = rings[-1]
    faces.append(tuple(top + i for i in range(n)))
    return verts, faces

def band_ring(poly, z, hgt, out):
    """A thin outward-offset strip around poly between z and z+hgt (window band)."""
    n = len(poly)
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n
    verts = []
    for (x, y) in poly:
        dx, dy = x - cx, y - cy
        d = math.hypot(dx, dy) or 1.0
        f = 1.0 + out / d
        verts.append((cx + dx * f, cy + dy * f, z))
    for (x, y) in poly:
        dx, dy = x - cx, y - cy
        d = math.hypot(dx, dy) or 1.0
        f = 1.0 + out / d
        verts.append((cx + dx * f, cy + dy * f, z + hgt))
    faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    return verts, faces

def chamfer_ring(poly, h, bevel, inset, out=0.008):
    """The chamfer band between z=h-bevel (outset) and z=h (inset), as a light surface."""
    n = len(poly)
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n
    verts = []
    for ins, z in ((-out, h - bevel), (inset - out, h + out * 0.5)):
        for (x, y) in poly:
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy) or 1.0
            f = max(0.0, 1.0 - ins / d)
            verts.append((cx + dx * f, cy + dy * f, z))
    faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    return verts, faces

def light_geometry(poly, h, bevel, inset):
    """Chamfer edge light plus window bands. Returns verts, faces."""
    verts, faces = [], []
    def add(v, f):
        base = len(verts)
        verts.extend(v)
        faces.extend(tuple(base + i for i in face) for face in f)
    v, f = chamfer_ring(poly, h, bevel, inset)
    add(v, f)
    # window bands every 0.55 units
    z = 0.32
    while z + 0.23 < h - bevel - 0.18:
        v, f = band_ring(poly, z, 0.22, 0.012)
        add(v, f)
        z += 0.5
    return verts, faces

# ---------------------------------------------------------------- scene helpers
scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
coll = bpy.data.collections.new("city")
scene.collection.children.link(coll)

MAT_BODY = None
MAT_LIGHT = None
MAT_ROAD = None
def materials():
    global MAT_BODY, MAT_LIGHT, MAT_ROAD
    if MAT_BODY:
        return
    m = bpy.data.materials.new("vc_body")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.38
    bsdf.inputs["Metallic"].default_value = 0.28
    bsdf.inputs["Specular IOR Level"].default_value = 0.4
    MAT_BODY = m
    m2 = bpy.data.materials.new("vc_light")
    m2.use_nodes = True
    nt = m2.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.05
    bsdf.inputs["Roughness"].default_value = 1.0
    MAT_LIGHT = m2
    m3 = bpy.data.materials.new("vc_road")
    m3.use_nodes = True
    nt = m3.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    info = nt.nodes.new("ShaderNodeObjectInfo")
    nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(info.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 0.45
    MAT_ROAD = m3

def new_object(name, verts, faces, color, loc=(0, 0, 0), emissive=False, road=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.color = col4(color)
    materials()
    me.materials.append(MAT_ROAD if road else (MAT_LIGHT if emissive else MAT_BODY))
    coll.objects.link(ob)
    return ob

# ---------------------------------------------------------------- build
def build_ground():
    b = layout["bounds"]
    minx, miny, maxx, maxy = b[0] - 400, b[1] - 400, b[2] + 400, b[3] + 400
    verts = [(minx, miny, 0), (maxx, miny, 0), (maxx, maxy, 0), (minx, maxy, 0)]
    new_object("ground", verts, [(0, 1, 2, 3)], NIGHT)
    # hairline grid
    gv, gf = [], []
    step = 4.0
    w = 0.008
    x = math.floor(minx / step) * step
    while x <= maxx:
        base = len(gv)
        gv += [(x - w, miny, 0.004), (x + w, miny, 0.004), (x + w, maxy, 0.004), (x - w, maxy, 0.004)]
        gf.append((base, base + 1, base + 2, base + 3))
        x += step
    y = math.floor(miny / step) * step
    while y <= maxy:
        base = len(gv)
        gv += [(minx, y - w, 0.004), (maxx, y - w, 0.004), (maxx, y + w, 0.004), (minx, y + w, 0.004)]
        gf.append((base, base + 1, base + 2, base + 3))
        y += step
    new_object("grid", gv, gf, GRID)

def rounded_rect(hw, hh, r, seg=6):
    pts = []
    corners = [(hw - r, hh - r, 0), (-hw + r, hh - r, 90), (-hw + r, -hh + r, 180), (hw - r, -hh + r, 270)]
    for cx, cy, a0 in corners:
        for k in range(seg + 1):
            a = math.radians(a0 + 90 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts

def build_plateaus():
    for d, info in DISTRICTS.items():
        if info["shape"] == "disc":
            r = info["rx"]
            poly = [(r * math.cos(2 * math.pi * i / 64), r * math.sin(2 * math.pi * i / 64)) for i in range(64)]
        else:
            poly = rounded_rect(info["rx"], info["ry"], 2.5)
        z = info["z"]
        verts, faces = extrude_bevel(poly, z, min(0.5, z * 0.6), min(0.9, z * 0.9), profile=4)
        c = lerp(NIGHT, BASE, 0.14)
        if d == "core":
            c = lerp(NIGHT, BONE, 0.22)
        new_object("plateau_" + d, verts, faces, c, loc=(info["cx"], info["cy"], 0))
    build_environment(DESIGN, layout, new_object, hex_rgb)

def build_buildings(week, animate=False):
    """Creates body (+ light) objects for every node that exists at `week`.
    With animate=True all nodes are created and keyframed over the 13 weeks."""
    bodies = {}
    lights = {}
    for nid, n in NODES.items():
        state, light = light_state(n, week)
        if state == "absent" and not animate:
            continue
        poly, h = building_shape(n, "foundation" if n["created"] is None else "lit")
        x, y = POS[nid]
        z = plateau_z(n["district"])
        bevel = min(0.12, h * 0.25)
        inset = min(0.06, min(abs(p[0]) for p in poly) * 0.35 + 0.01)
        body_mesh, light_mesh = detailed_geometry(n, DESIGN["buildings"][str(nid)])
        v, f = body_mesh.v, body_mesh.f
        body = body_color(n, state, light)
        ob = new_object("b%04d" % nid, v, f, body, loc=(x, y, z))
        bodies[nid] = ob
        if n["created"] is not None and n["status"] == "active":
            lv, lf = light_mesh.v, light_mesh.f
            if lf:
                lc = light_color(n, "lit", max(light, 0.15), body)
                if state != "lit":
                    lc = body
                lob = new_object("l%04d" % nid, lv, lf, lc, loc=(x, y, z), emissive=True)
                lights[nid] = lob
    return bodies, lights

ROAD_W = {"intra": 0.02, "inter": 0.012}
ROAD_MIX = {"intra": 0.07, "inter": 0.025}

def build_roads(week, animate=False):
    """One hairline mesh per appearance week."""
    buckets = {}
    for a, b in EDGES:
        na, nb = NODES[a], NODES[b]
        w = max(appear_week(na), appear_week(nb))
        if w > week and not animate:
            continue
        kind = "intra" if na["district"] == nb["district"] else "inter"
        buckets.setdefault((w, kind), []).append((a, b))
    objs = {}
    for (w, kind), es in buckets.items():
        hw = ROAD_W[kind]
        verts, faces = [], []
        for a, b in es:
            xa, ya = POS[a]; xb, yb = POS[b]
            za = plateau_z(NODES[a]["district"]) + 0.02
            zb = plateau_z(NODES[b]["district"]) + 0.02
            dx, dy = xb - xa, yb - ya
            d = math.hypot(dx, dy) or 1.0
            px, py = -dy / d * hw, dx / d * hw
            base = len(verts)
            verts += [(xa + px, ya + py, za), (xa - px, ya - py, za), (xb - px, yb - py, zb), (xb + px, yb + py, zb)]
            faces.append((base, base + 1, base + 2, base + 3))
        c = lerp(NIGHT, SIGNAL, ROAD_MIX[kind])
        objs[(w, kind)] = new_object("roads_w%02d_%s" % (w, kind), verts, faces, c, road=True)
    return objs

# ---------------------------------------------------------------- camera and light
def city_extent():
    b = layout["bounds"]
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, (b[2] - b[0]), (b[3] - b[1])

def city_points():
    """Sample points on every plateau outline, at ground and at roof height, for camera fitting."""
    pts = []
    for d, info in DISTRICTS.items():
        for zz in (0.0, info["z"] + 1.2):
            if info["shape"] == "disc":
                for i in range(16):
                    a = 2 * math.pi * i / 16
                    pts.append(Vector((info["cx"] + info["rx"] * math.cos(a), info["cy"] + info["ry"] * math.sin(a), zz)))
            else:
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        pts.append(Vector((info["cx"] + sx * info["rx"], info["cy"] + sy * info["ry"], zz)))
    for nid, n in NODES.items():
        f = DESIGN["buildings"][str(nid)]
        x, y = POS[nid]
        pts.append(Vector((x, y, plateau_z(n["district"]) + f["h"] * 1.12 + .7)))
    return pts

def look_at(eye, target, roll_deg):
    f = (target - eye).normalized()
    r = f.cross(Vector((0, 0, 1))).normalized()
    u = r.cross(f).normalized()
    rot = Matrix((r, u, -f)).transposed().to_4x4()
    return rot @ Matrix.Rotation(math.radians(roll_deg), 4, "Z")

def camera_matrix(azimuth_deg, elevation_deg, roll_deg, dist, target):
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    eye = target + Vector((dist * math.cos(el) * math.cos(az), dist * math.cos(el) * math.sin(az), dist * math.sin(el)))
    return Matrix.Translation(eye) @ look_at(eye, target, roll_deg), eye

def fit_distance(azimuth_deg, elevation_deg, roll_deg, target, lens, res_x, res_y, margin=0.94):
    pts = city_points()
    hx = 18.0
    hy = 18.0 * res_y / res_x
    lo, hi = 10.0, 3000.0
    for _ in range(40):
        mid = (lo + hi) / 2
        m, eye = camera_matrix(azimuth_deg, elevation_deg, roll_deg, mid, target)
        inv = m.inverted()
        worst = 0.0
        for p in pts:
            v = inv @ p
            if v.z >= -0.01:
                worst = 9.0
                break
            worst = max(worst, abs(v.x / -v.z) * lens / hx, abs(v.y / -v.z) * lens / hy)
        if worst > margin:
            lo = mid
        else:
            hi = mid
    return hi

CAM = {"azimuth": -112.0, "elevation": 32.0, "roll": 0.0, "lens": 39.0}

def build_camera(res_x=480, res_y=270, target_shift=(0.0, 3.0, 0.0)):
    cx, cy, w, h = city_extent()
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = CAM["lens"]
    cam_data.sensor_width = 36.0
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.clip_end = 3000
    cam = bpy.data.objects.new("cam", cam_data)
    coll.objects.link(cam)
    scene.camera = cam
    target = Vector((cx + target_shift[0], cy + target_shift[1], 1.0 + target_shift[2]))
    hx, hy = 18.0, 18.0 * res_y / res_x
    for _ in range(6):
        dist = fit_distance(CAM["azimuth"], CAM["elevation"], CAM["roll"], target, CAM["lens"], res_x, res_y)
        m, eye = camera_matrix(CAM["azimuth"], CAM["elevation"], CAM["roll"], dist, target)
        inv = m.inverted()
        xs, ys = [], []
        for p in city_points():
            v = inv @ p
            xs.append(v.x / -v.z * CAM["lens"] / hx)
            ys.append(v.y / -v.z * CAM["lens"] / hy)
        ox, oy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        # move the aim point in world space along the camera's right/up axes, scaled by distance
        right = Vector((m[0][0], m[1][0], m[2][0]))
        up = Vector((m[0][1], m[1][1], m[2][1]))
        target = target + right * (ox * hx / CAM["lens"] * dist) + up * (oy * hy / CAM["lens"] * dist)
    dist = fit_distance(CAM["azimuth"], CAM["elevation"], CAM["roll"], target, CAM["lens"], res_x, res_y)
    m, eye = camera_matrix(CAM["azimuth"], CAM["elevation"], CAM["roll"], dist, target)
    cam.matrix_world = m
    print("ndc x %.2f..%.2f y %.2f..%.2f" % (min(xs), max(xs), min(ys), max(ys)))
    print("camera dist %.1f eye %s" % (dist, [round(v, 1) for v in eye]))
    return cam, target, dist

def build_lights_eevee():
    sun_data = bpy.data.lights.new("sun", "SUN")
    sun_data.energy = 3.2
    sun_data.color = (0.92, 0.88, 1.0)
    sun_data.angle = math.radians(8)
    sun = bpy.data.objects.new("sun", sun_data)
    sun.rotation_euler = (math.radians(50), 0, math.radians(-40))
    coll.objects.link(sun)
    fill_data = bpy.data.lights.new("fill", "SUN")
    fill_data.energy = 0.9
    fill_data.color = to_linear(SIGNAL)
    fill = bpy.data.objects.new("fill", fill_data)
    fill.rotation_euler = (math.radians(60), 0, math.radians(140))
    coll.objects.link(fill)

# ---------------------------------------------------------------- render settings
def setup_world():
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    scene.world = world
    world.color = to_linear(NIGHT)
    try:
        nt = world.node_tree
        bg = nt.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = col4(NIGHT)
            bg.inputs["Strength"].default_value = 0.6
    except Exception as e:
        print("world nodes:", e)

def setup_workbench(res_x, res_y):
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light = "STUDIO"
    sh.studio_light = "paint.sl"
    sh.color_type = "OBJECT"
    sh.show_shadows = True
    sh.shadow_intensity = 0.35
    sh.show_cavity = True
    sh.cavity_type = "BOTH"
    sh.cavity_ridge_factor = 1.6
    sh.cavity_valley_factor = 1.0
    sh.curvature_ridge_factor = 1.2
    sh.curvature_valley_factor = 1.0
    sh.show_specular_highlight = False
    sh.show_object_outline = False
    sh.background_type = "WORLD"
    sh.use_world_space_lighting = False
    scene.display.render_aa = "16"
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    except Exception as e:
        print("view transform:", e)
    # paint.sl lights a horizontal white face to 0.74 linear; lift so palette values land exactly
    scene.view_settings.exposure = math.log2(1.0 / 0.74)

def setup_eevee(res_x, res_y, samples=64):
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = samples
    scene.eevee.use_shadows = True
    scene.eevee.use_raytracing = False
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    except Exception as e:
        print("view transform:", e)

def setup_compositor(fog_near, fog_far, bloom=False):
    """Depth fog toward DEEP (and bloom for EEVEE) with the 5.x compositing node group."""
    try:
        scene.view_layers[0].use_pass_z = True
        ng = bpy.data.node_groups.new("vc_comp", "CompositorNodeTree")
        scene.compositing_node_group = ng
        scene.render.use_compositing = True
        try:
            ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        except Exception as e:
            print("interface socket:", e)
        rl = ng.nodes.new("CompositorNodeRLayers")
        out = ng.nodes.new("NodeGroupOutput")
        img = rl.outputs["Image"]
        if bloom:
            try:
                gl = ng.nodes.new("CompositorNodeGlare")
                try:
                    gl.inputs["Type"].default_value = "Bloom"
                except Exception as e:
                    print("glare type:", e)
                for k, v in (("Threshold", 0.6), ("Strength", 0.3), ("Size", 0.45), ("Saturation", 1.0), ("Smoothness", 0.3)):
                    if k in gl.inputs:
                        try:
                            gl.inputs[k].default_value = v
                        except Exception as e:
                            print("glare input", k, e)
                try:
                    gl.inputs["Quality"].default_value = "High"
                except Exception:
                    pass
                ng.links.new(img, gl.inputs["Image"])
                img = gl.outputs["Image"]
            except Exception as e:
                print("glare node:", e)
        # depth -> fog factor (5.x compositor shares the shader Map Range / Mix nodes)
        mr = None
        for ident in ("ShaderNodeMapRange", "CompositorNodeMapRange"):
            try:
                mr = ng.nodes.new(ident)
                break
            except Exception as e:
                print("map range node", ident, e)
        mr.inputs["From Min"].default_value = fog_near
        mr.inputs["From Max"].default_value = fog_far
        mr.inputs["To Min"].default_value = 0.0
        mr.inputs["To Max"].default_value = FOG_MAX
        try:
            mr.interpolation_type = "SMOOTHSTEP"
        except Exception:
            pass
        mr.clamp = True
        ng.links.new(rl.outputs["Depth"], mr.inputs["Value"])
        mix = None
        for ident in ("ShaderNodeMix", "CompositorNodeMixRGB"):
            try:
                mix = ng.nodes.new(ident)
                break
            except Exception as e:
                print("mix node", ident, e)
        if mix.bl_idname == "ShaderNodeMix":
            mix.data_type = "RGBA"
            ng.links.new(mr.outputs[0], mix.inputs["Factor"])
            ng.links.new(img, mix.inputs[6])
            mix.inputs[7].default_value = col4(DEEP)
            res = mix.outputs[2]
        else:
            ng.links.new(mr.outputs[0], mix.inputs[0])
            ng.links.new(img, mix.inputs[1])
            mix.inputs[2].default_value = col4(DEEP)
            res = mix.outputs[0]
        ng.links.new(res, out.inputs[0])
        print("compositor ok")
    except Exception as e:
        print("compositor FAILED:", repr(e))
        scene.render.use_compositing = False

def render_still(path):
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.filepath = path
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print("rendered %s in %.1fs" % (os.path.basename(path), time.time() - t))

def save_blend():
    p = os.path.join(HERE, "city.blend")
    bpy.ops.wm.save_as_mainfile(filepath=p, compress=True)
    print("saved city.blend")

# ---------------------------------------------------------------- modes
FOG_MAX = 0.55

def fog_bounds(cam, dist):
    eye = cam.matrix_world.translation
    ds = [(p - eye).length for p in city_points()]
    near, far = min(ds), max(ds)
    return near + (far - near) * 0.15, far + (far - near) * 0.35

def mode_iter():
    build_ground()
    build_plateaus()
    bodies, lights = build_buildings(WEEK)
    roads = build_roads(WEEK)
    cam, target, dist = build_camera()
    setup_world()
    setup_workbench(480, 270)
    near, far = fog_bounds(cam, dist)
    setup_compositor(near, far)
    print("built %d bodies, %d lights, %d road buckets in %.1fs" % (len(bodies), len(lights), len(roads), time.time() - T0))
    out = arg("--out", "")
    if out:
        render_still(out)
    else:
        render_still(os.path.join(RENDERS, "iter_%02d.png" % ITER))
        save_blend()

if MODE == "iter":
    mode_iter()
elif MODE == "calib":
    # white ground + white box under the same workbench settings, to measure the lighting gain
    new_object("wground", [(-400, -400, 0), (400, -400, 0), (400, 400, 0), (-400, 400, 0)], [(0, 1, 2, 3)], (1, 1, 1))
    v, f = extrude_bevel(rect(30, 30), 20, 0.5, 0.5)
    new_object("wbox", v, f, (1, 1, 1), loc=(-30, 0, 0))
    cam, target, dist = build_camera()
    setup_world()
    setup_workbench(480, 270)
    scene.render.use_compositing = False
    for preset in ("Default", "basic.sl", "outdoor.sl", "paint.sl", "rim.sl", "studio.sl"):
        scene.display.shading.studio_light = preset
        render_still(os.path.join(RENDERS, "calib_%s.png" % preset.split(".")[0]))
elif MODE == "probe":
    cam, target, dist = build_camera()
    inv = cam.matrix_world.inverted()
    hx, hy = 18.0, 18.0 * 270 / 480
    xs, ys = [], []
    for p in city_points():
        v = inv @ p
        xs.append(v.x / -v.z * CAM["lens"] / hx); ys.append(v.y / -v.z * CAM["lens"] / hy)
    print("ndc x %.2f..%.2f  y %.2f..%.2f" % (min(xs), max(xs), min(ys), max(ys)))
    print("render res", scene.render.resolution_x, scene.render.resolution_y, "sensor", cam.data.sensor_width, cam.data.sensor_fit, cam.data.lens)

# ---------------------------------------------------------------- final phase
FPS = 24
FRAMES = 144

def week_frame(w):
    return 1 + int(round(w * (FRAMES - 1) / float(LAST_WEEK)))

def set_ffmpeg(path, res_x, res_y):
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = FRAMES
    try:
        scene.render.image_settings.media_type = "VIDEO"
    except Exception as e:
        print("media_type:", e)
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    scene.render.ffmpeg.gopsize = 12
    scene.render.filepath = path

def finish_movie(stem, final_name):
    """Blender appends the frame range to movie names; rename to the requested file."""
    import glob
    cands = sorted(glob.glob(os.path.join(HERE, stem + "*.mp4")), key=os.path.getmtime)
    if cands:
        dst = os.path.join(HERE, final_name)
        if os.path.exists(dst):
            os.remove(dst)
        os.rename(cands[-1], dst)
        print("wrote", final_name, os.path.getsize(dst), "bytes")

def mode_final():
    build_ground()
    build_plateaus()
    bodies, lights = build_buildings(LAST_WEEK)
    roads = build_roads(LAST_WEEK)
    for road in roads.values():
        road.hide_render = True
        road.hide_set(True)
    cam, target, dist = build_camera(1920, 1080)
    setup_world()
    build_lights_eevee()
    # Warm and cool practical lights keep the street-facing detail readable in EEVEE.
    for route_index in (0, 1, 9):
        route = DESIGN["routes"][route_index]
        for i in range(0, len(route["points"]), 44):
            x,y = route["points"][i]
            light_data = bpy.data.lights.new("Boulevard practical", 'POINT')
            light_data.energy = 9
            light_data.color = hex_rgb(DESIGN["palette"][route["district"]])
            light_data.shadow_soft_size = .65
            light_data.use_shadow = False
            practical = bpy.data.objects.new("Boulevard practical", light_data)
            practical.location = (x,y,route["z"]+.8)
            coll.objects.link(practical)
    setup_eevee(1920, 1080, samples=int(arg("--samples", "64")))
    near, far = fog_bounds(cam, dist)
    setup_compositor(near, far, bloom=True)
    print("built for final in %.1fs" % (time.time() - T0))
    render_still(os.path.join(HERE, "final.png"))
    # Keep a second camera in the editable scene for inspecting the street architecture.
    route = DESIGN["routes"][0]
    points = route["points"]
    i = int(len(points)*.28)
    x,y = points[i]
    tx,ty = points[(i+24) % len(points)]
    street_data = bpy.data.cameras.new("Street view - Lantern avenue")
    street_data.lens = 20
    street_data.clip_start = .03
    street_cam = bpy.data.objects.new(street_data.name, street_data)
    coll.objects.link(street_cam)
    street_cam.location = (x,y,route["z"]+.64)
    street_cam.rotation_euler = (Vector((tx,ty,route["z"]+.86))-street_cam.location).to_track_quat('-Z','Y').to_euler()
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.shading.type = 'MATERIAL'
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "city.blend"), compress=True)
    scene.camera = street_cam
    scene.render.resolution_x, scene.render.resolution_y = 1440, 900
    render_still(os.path.join(RENDERS, "street-level.png"))

def keyframe_visibility(ob, f_appear, rise=10):
    if f_appear <= 1:
        return
    ob.hide_render = True
    ob.keyframe_insert("hide_render", frame=1)
    ob.hide_render = False
    ob.keyframe_insert("hide_render", frame=max(1, f_appear - rise))
    ob.scale = (1.0, 1.0, 0.02)
    ob.keyframe_insert("scale", frame=max(1, f_appear - rise))
    ob.scale = (1.0, 1.0, 1.0)
    ob.keyframe_insert("scale", frame=f_appear)

def mode_timelapse():
    build_ground()
    build_plateaus()
    bodies, lights = build_buildings(LAST_WEEK, animate=True)
    roads = build_roads(LAST_WEEK, animate=True)
    for nid, ob in bodies.items():
        n = NODES[nid]
        keyframe_visibility(ob, week_frame(appear_week(n)))
        lob = lights.get(nid)
        if lob is not None:
            keyframe_visibility(lob, week_frame(appear_week(n)))
        for w in range(LAST_WEEK + 1):
            state, light = light_state(n, w)
            if state == "absent":
                continue
            body = body_color(n, state, light)
            ob.color = col4(body)
            ob.keyframe_insert("color", frame=week_frame(w))
            if lob is not None:
                lc = light_color(n, "lit", max(light, 0.15), body) if state == "lit" else body
                lob.color = col4(lc)
                lob.keyframe_insert("color", frame=week_frame(w))
    for (w, kind), ob in roads.items():
        keyframe_visibility(ob, week_frame(w), rise=4)
    cam, target, dist = build_camera(640, 360)
    setup_world()
    setup_workbench(640, 360)
    near, far = fog_bounds(cam, dist)
    setup_compositor(near, far)
    set_ffmpeg(os.path.join(HERE, "timelapse_"), 640, 360)
    print("timelapse built in %.1fs, rendering %d frames" % (time.time() - T0, FRAMES))
    t = time.time()
    bpy.ops.render.render(animation=True)
    print("animation rendered in %.1fs" % (time.time() - t))
    finish_movie("timelapse_", "timelapse.mp4")

def mode_turntable():
    build_ground()
    build_plateaus()
    bodies, lights = build_buildings(LAST_WEEK)
    roads = build_roads(LAST_WEEK)
    cam, target, dist = build_camera(640, 360)
    dmax = dist
    for k in range(12):
        az = CAM["azimuth"] + 360.0 * k / 12
        dmax = max(dmax, fit_distance(az, CAM["elevation"], CAM["roll"], target, CAM["lens"], 640, 360))
    cam.rotation_mode = "XYZ"
    for f in range(1, FRAMES + 1):
        az = CAM["azimuth"] + 360.0 * (f - 1) / FRAMES
        m, eye = camera_matrix(az, CAM["elevation"], CAM["roll"], dmax, target)
        cam.matrix_world = m
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
    # one keyframe per frame, so interpolation mode is irrelevant
    setup_world()
    setup_workbench(640, 360)
    near, far = fog_bounds(cam, dmax)
    setup_compositor(near * 0.9, far * 1.1)
    set_ffmpeg(os.path.join(HERE, "turntable_"), 640, 360)
    print("turntable built in %.1fs" % (time.time() - T0))
    t = time.time()
    bpy.ops.render.render(animation=True)
    print("animation rendered in %.1fs" % (time.time() - t))
    finish_movie("turntable_", "turntable.mp4")

def mode_glb():
    """Export the same detailed buildings and streets used in the Blender scene."""
    build_plateaus()
    build_buildings(LAST_WEEK)
    # Object Info colors are not portable to glTF. Bake them and batch by material.
    buckets = {False: ([], [], []), True: ([], [], [])}
    originals = list(coll.objects)
    for ob in originals:
        if ob.type != "MESH":
            continue
        is_glow = ob.data.materials[0] == MAT_LIGHT
        verts, faces, colors = buckets[is_glow]
        base = len(verts)
        verts.extend(tuple(v.co + ob.location) for v in ob.data.vertices)
        for poly in ob.data.polygons:
            faces.append(tuple(base + i for i in poly.vertices))
            colors.extend(tuple(ob.color) * len(poly.vertices))
    for ob in originals:
        bpy.data.objects.remove(ob, do_unlink=True)
    for emissive, (verts, faces, colors) in buckets.items():
        me = bpy.data.meshes.new("neon" if emissive else "architecture")
        me.from_pydata(verts, [], faces)
        me.update()
        attr = me.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="CORNER")
        attr.data.foreach_set("color", colors)
        me.color_attributes.active_color = attr
        mat = bpy.data.materials.new("neon_vertex" if emissive else "city_vertex")
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        vertex = nt.nodes.new("ShaderNodeVertexColor")
        vertex.layer_name = "Col"
        nt.links.new(vertex.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = .38
        if emissive:
            nt.links.new(vertex.outputs["Color"], bsdf.inputs["Emission Color"])
            bsdf.inputs["Emission Strength"].default_value = 1.05
        me.materials.append(mat)
        ob = bpy.data.objects.new(me.name, me)
        coll.objects.link(ob)
    path = os.path.join(HERE, "city.glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=False,
        export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
        export_apply=True, export_yup=True, export_animations=False, export_vertex_color="ACTIVE")
    print("city.glb", os.path.getsize(path), "bytes")

if MODE == "final":
    mode_final()
elif MODE == "timelapse":
    mode_timelapse()
elif MODE == "turntable":
    mode_turntable()
elif MODE == "glb":
    mode_glb()
print("total %.1fs" % (time.time() - T0))
