"""Detailed procedural architecture and street furniture for the night city."""
import math


class Mesh:
    def __init__(self):
        self.v, self.f = [], []

    def face(self, points):
        i = len(self.v)
        self.v.extend(points)
        self.f.append(tuple(range(i, i+len(points))))

    def prism(self, poly, z0, z1, scale0=1, scale1=1, cap=True):
        for i, a in enumerate(poly):
            b = poly[(i+1) % len(poly)]
            self.face([(a[0]*scale0,a[1]*scale0,z0), (b[0]*scale0,b[1]*scale0,z0),
                       (b[0]*scale1,b[1]*scale1,z1), (a[0]*scale1,a[1]*scale1,z1)])
        if cap:
            self.face([(x*scale1,y*scale1,z1) for x,y in poly])

    def box(self, x0,y0,z0,x1,y1,z1):
        self.prism([(x0,y0),(x1,y0),(x1,y1),(x0,y1)],z0,z1)


def geometry(n, form):
    """Return local body/light meshes. All detail grows with the building in timelapse."""
    body, light = Mesh(), Mesh()
    w,d,h,kind = (form[k] for k in ("w","d","h","kind"))
    poly = [(-w/2,-d/2),(w/2,-d/2),(w/2,d/2),(-w/2,d/2)]
    if kind in ("hex","cyl","dome"):
        sides = 6 if kind == "hex" else 16
        poly = [(math.cos(i*math.tau/sides)*w/2,math.sin(i*math.tau/sides)*d/2) for i in range(sides)]
    body.prism(poly,0,min(.18,h*.12),1.1,1.1)
    tiers = [(0, .94, 1)]
    if kind == "tower": tiers=[(0,.55,1),(.55,.94,.72)]
    if kind == "stepped": tiers=[(0,.44,1),(.44,.76,.72),(.76,.97,.44)]
    if kind == "spire": tiers=[(0,.69,1),(.69,.85,.8),(.85,.97,.46)]
    if kind == "dome":
        body.prism(poly,0,h*.4)
        for j in range(8):
            a,b=j/8*math.pi/2,(j+1)/8*math.pi/2
            body.prism(poly,h*(.4+.6*math.sin(a)),h*(.4+.6*math.sin(b)),math.cos(a),max(.015,math.cos(b)))
            if j%2==0: light.prism(poly,h*(.4+.6*math.sin(a)),h*(.4+.6*math.sin(a))+.018,math.cos(a)+.008,math.cos(a)+.008,False)
        return body,light
    for start,end,scale in tiers:
        body.prism(poly,h*start,h*end,scale,scale)
        if kind != "found":
            light.prism(poly,h*end,h*end+.035,scale+.014,scale+.014,False)
        z=h*start+.26
        row=0
        while z<h*end-.15 and kind not in ("found",):
            for edge,a in enumerate(poly):
                b=poly[(edge+1)%len(poly)]
                ax,ay=a[0]*scale,a[1]*scale
                bx,by=b[0]*scale,b[1]*scale
                length=math.hypot(bx-ax,by-ay)
                columns=max(1,int(length/.19))
                nx,ny=(by-ay)/length*.009,-(bx-ax)/length*.009
                for col in range(columns):
                    if (n["id"]*17+row*7+col*13+edge*3)%11<3: continue
                    u0,u1=(col+.16)/columns,(col+.74)/columns
                    x0,y0=ax+(bx-ax)*u0+nx,ay+(by-ay)*u0+ny
                    x1,y1=ax+(bx-ax)*u1+nx,ay+(by-ay)*u1+ny
                    light.face([(x0,y0,z),(x1,y1,z),(x1,y1,z+.18),(x0,y0,z+.18)])
            z+=.46;row+=1
    if kind == "found":
        return body,Mesh()
    # A dark roof with ventilation plant, selective edge lights and a small aerial.
    body.prism(poly,h*.94,h,tiers[-1][2],tiers[-1][2]*.92)
    body.box(-w*.23,-d*.23,h,w*.08,d*.09,h+.16)
    body.box(w*.17,d*.08,h,w*.30,d*.30,h+.10)
    if h>6:
        body.box(-.013,-.013,h,.013,.013,h+.65)
        light.box(-.025,-.025,h+.64,.025,.025,h+.69)
    if kind in ("shop","slab","sign","tower"):
        light.prism(poly,.43,.46,1.12,1.12,False)
        body.prism(poly,.46,.51,1.12,1.12)
        # Facade mullions and ribs make reflections read as glass between metal.
        for x in (-w*.42,w*.42):
            for y in (-d*.514,d*.514):
                body.box(x-.014,y-.012,.54,x+.014,y+.012,h*.52)
    if kind == "slab":
        light.box(-w*.40,-d*.515,h*.2,-w*.35,-d*.50,h*.85)
    if kind == "gable":
        body.prism(poly,h*.94,h*1.08,1,.12)
    if kind == "spire":
        body.prism(poly,h*.97,h*1.09,.46,.015)
    return body,light


def environment(design, layout, new_object, rgb):
    """Batched road surfaces, sidewalk curbs, pedestrians, lamps and vehicles."""
    pavement, asphalt, paint, furniture = Mesh(),Mesh(),Mesh(),Mesh()
    windows = {d:Mesh() for d in design["palette"]}
    people = [Mesh() for _ in range(5)]
    def strip(mesh,points,z,width,offset=0):
        left,right=[],[]
        for i,(x,y) in enumerate(points):
            a,b=points[i-1],points[(i+1)%len(points)]
            dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
            px,py=-dy/length,dx/length
            left.append((x+px*(offset-width/2),y+py*(offset-width/2),z))
            right.append((x+px*(offset+width/2),y+py*(offset+width/2),z))
        for i in range(len(points)):
            j=(i+1)%len(points);mesh.face([left[i],left[j],right[j],right[i]])
    for ri,route in enumerate(design["routes"]):
        pts,z=route["points"],route["z"]
        width=.54 if route["district"]=="episodic" else .88
        strip(pavement,pts,z-.012,width+.26)
        strip(asphalt,pts,z+.005,width)
        glow=windows[route["district"]]
        strip(glow,pts,z+.02,.013,width/2+.025)
        strip(glow,pts,z+.02,.013,-width/2-.025)
        travelled=0;next_lamp=1.5;next_person=.8;next_car=2.8;next_dash=.4
        for i,(x,y) in enumerate(pts):
            nxt=pts[(i+1)%len(pts)];dx,dy=nxt[0]-x,nxt[1]-y;length=math.hypot(dx,dy)
            if length<1e-6: continue
            px,py=-dy/length,dx/length
            if travelled>=next_dash:
                paint.face([(x-.013*px,y-.013*py,z+.022),(x+.013*px,y+.013*py,z+.022),
                            (x+.013*px+dx/length*.3,y+.013*py+dy/length*.3,z+.022),
                            (x-.013*px+dx/length*.3,y-.013*py+dy/length*.3,z+.022)])
                next_dash+=1.8
            if travelled>=next_lamp:
                lx,ly=x+px*(width/2+.07),y+py*(width/2+.07)
                furniture.box(lx-.023,ly-.023,z,lx+.023,ly+.023,z+.92)
                glow.box(lx-.08,ly-.08,z+.92,lx+.08,ly+.08,z+1.04)
                next_lamp+=4.6
            if travelled>=next_person:
                side=1 if i%2 else -1
                offset=min(width/2+.04,route["clearance"]-.12)
                x0,y0=x+px*offset*side,y+py*offset*side
                person=people[i%5]
                person.box(x0-.044,y0-.035,z+.14,x0+.044,y0+.035,z+.275)
                person.box(x0-.027,y0-.027,z+.278,x0+.027,y0+.027,z+.338)
                for sx in (-1,1):
                    furniture.box(x0+sx*.025-.013,y0-.018,z+.02,x0+sx*.025+.013,y0+.018,z+.15)
                next_person+=2.8+(i%3)*.32
            if travelled>=next_car:
                furniture.box(x-.09,y-.17,z+.04,x+.09,y+.17,z+.15)
                furniture.box(x-.065,y-.10,z+.15,x+.065,y+.10,z+.22)
                glow.box(x-.07,y+.15,z+.07,x+.07,y+.17,z+.11)
                next_car+=6.7
            travelled+=length
    for name,mesh,color,emit in [("sidewalks",pavement,"#263544",False),("wet_asphalt",asphalt,"#152331",False),
                                  ("lane_markings",paint,"#868e89",False),("street_furniture",furniture,"#354657",False)]:
        new_object(name,mesh.v,mesh.f,rgb(color),emissive=emit)
    for d,mesh in windows.items():
        new_object("street_neon_"+d,mesh.v,mesh.f,rgb(design["palette"][d]),emissive=True)
    for i,mesh in enumerate(people):
        new_object("citizens_"+str(i),mesh.v,mesh.f,rgb(["#a9b7c3","#d98388","#5fbeb5","#8b80b7","#d9b573"][i]))
