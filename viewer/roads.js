// Roads (C6, C14): the road network rebuilt from the page data. design.py leaves out what can be
// rebuilt (its publish() and expand() are the reference): graph ids and ports, the turn arcs through
// the junction fillets and the tour polyline from its graph steps. graph, bridges, rim and lake are the
// design data in layout coordinates (x, y, z up); tour.sample and surfaceAtRoad work in world
// coordinates (x, up, z = -y). The Archive east rim road's own stretch is drawn by city-life.js like every
// street; this file draws plain temporary decks for the Reef pier and island, then the bridges, and ends
// with the traffic routing on the graph (C5.4, C7.6).
const roadNet=(()=>{
  const D=DATA.design,bridges=D.bridges||[],ROAD_HALF=.44,RAD=Math.PI/180;
  if(!bridges.length||!D.graph||!D.tour)return null;
  const dist2=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
  function cumulative(points,closed){
    const s=[0];for(let i=1;i<points.length;i++)s.push(s[i-1]+dist2(points[i-1],points[i]));
    if(closed)s.push(s[s.length-1]+dist2(points[points.length-1],points[0]));
    return s;
  }
  // Python's bisect_right.
  function upper(a,x){let lo=0,hi=a.length;while(lo<hi){const mid=(lo+hi)>>1;if(x<a[mid])hi=mid;else lo=mid+1;}return lo;}
  function arc(cx,cy,r,a0,a1,step){
    const n=Math.max(2,Math.ceil(Math.abs((a1-a0)*RAD)*r/step)),out=[];
    for(let j=0;j<=n;j++){const a=(a0+(a1-a0)*j/n)*RAD;out.push([cx+r*Math.cos(a),cy+r*Math.sin(a)]);}
    return out;
  }
  // Fillets: the carriageway-edge tangency points on the ring and on the bridge.
  for(const b of bridges){
    b.spoke=b.from==='core';b.halfWidth=Math.round((b.width/2+b.sidewalk)*1000)/1000;
    for(const e of b.ends)for(const f of e.fillets){
      f.ring=[f.cx+f.r*Math.cos(f.a0*RAD),f.cy+f.r*Math.sin(f.a0*RAD)];
      f.bridge=[f.cx+f.r*Math.cos(f.a1*RAD),f.cy+f.r*Math.sin(f.a1*RAD)];
    }
  }
  // The graph: node ids and ports, bridge edge metadata, turn arcs.
  const graph=D.graph;
  graph.nodes.forEach((n,k)=>{n.id=k;n.ports=[];});
  graph.edges.forEach((e,k)=>{e.id=k;graph.nodes[e.a].ports.push([k,0]);graph.nodes[e.b].ports.push([k,1]);
    if(e.kind==='bridge'){const b=bridges[e.bridge];e.from=b.from;e.to=b.to;e.split=b.split;}});
  graph.turns.forEach((t,k)=>{
    const end=bridges[t.bridge].ends[t.end],f=end.fillets.find(q=>q.side===t.side);
    t.id=k;t.node=end.node;t.points=arc(f.cx,f.cy,f.r+ROAD_HALF,f.a0,f.a1,.1).map(p=>[p[0],p[1],end.z]);
    const c=cumulative(t.points,false);t.length=c[c.length-1];
  });
  // Edge centrelines, [x, y, z] from end a to end b (route_slice and polyline_at in design.py).
  const routeCum=new Map();
  function polylineAt(points,cum,s){
    const total=cum[cum.length-1];s%=total;s=Math.max(0,Math.min(total,s));
    const i=Math.max(0,Math.min(cum.length-2,upper(cum,s)-1)),a=points[i],b=points[(i+1)%points.length];
    const t=(s-cum[i])/(cum[i+1]-cum[i]||1e-9);
    return [a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];
  }
  function routeSlice(points,cum,s0,s1,z){
    const total=cum[cum.length-1],first=polylineAt(points,cum,s0),out=[[first[0],first[1],z]];
    let k=upper(cum,s0%total),base=s0-s0%total;
    for(;;){if(k>=points.length){k=0;base+=total;}if(base+cum[k]>=s1-1e-9)break;out.push([points[k][0],points[k][1],z]);k++;}
    const last=polylineAt(points,cum,s1);out.push([last[0],last[1],z]);
    return out;
  }
  function edgePoints(e){
    if(e.kind==='bridge')return bridges[e.bridge].points.map(p=>p.slice());
    if(e.kind==='link'){const st=D.streets[e.street];return st.points.map(p=>[p[0],p[1],st.z]);}
    const r=D.routes[e.route];if(!routeCum.has(e.route))routeCum.set(e.route,cumulative(r.points,true));
    return routeSlice(r.points,routeCum.get(e.route),e.s0,e.s1,r.z);
  }
  function cut(points,lo,hi){
    const cum=cumulative(points,false);lo=Math.max(0,lo);hi=Math.min(cum[cum.length-1],hi);
    const at=s=>{const i=Math.max(0,Math.min(cum.length-2,upper(cum,s)-1)),t=(s-cum[i])/(cum[i+1]-cum[i]||1e-12);
      return [0,1,2].map(j=>points[i][j]+(points[i+1][j]-points[i][j])*t);};
    const out=[at(lo)];for(let i=0;i<points.length;i++)if(lo+1e-9<cum[i]&&cum[i]<hi-1e-9)out.push(points[i].slice());
    out.push(at(hi));return out;
  }
  // The tour polyline (tour_points in design.py): each step's turn arc and trimmed edge, joined, then
  // resampled from s0 in count equal steps. Every published tour distance is measured on this polyline.
  const T=D.tour,steps=T.steps,dense=[];
  const add=pts=>{for(const p of pts)if(!dense.length||dist2(dense[dense.length-1],p)>=1e-6)dense.push(p);};
  steps.forEach(([edge,frm,turn,tdir],i)=>{
    const e=graph.edges[edge],nxt=steps[(i+1)%steps.length],key=e.kind==='bridge'?'trimBridge':'trimRing';
    if(turn>=0){const pts=graph.turns[turn].points.map(p=>p.slice());add(tdir>0?pts:pts.reverse());}
    const trim0=turn>=0?graph.turns[turn][key]:0,trim1=nxt[2]>=0?graph.turns[nxt[2]][key]:0;
    let pts=edgePoints(e);if(frm===1)pts=pts.reverse();
    const c=cumulative(pts,false);add(cut(pts,trim0,c[c.length-1]-trim1));
  });
  if(dist2(dense[dense.length-1],dense[0])<1e-6)dense.pop();
  const n=dense.length,dcum=cumulative(dense,false),dtotal=dcum[n-1]+dist2(dense[n-1],dense[0]),m=T.count;
  const tx=new Float64Array(m),ty=new Float64Array(m),tz=new Float64Array(m),tcum=new Float64Array(m+1);
  for(let k=0;k<m;k++){
    const s=(T.s0+dtotal*k/m)%dtotal,j=Math.max(0,Math.min(n-1,upper(dcum,s)-1)),a=dense[j],b=dense[(j+1)%n];
    const seg=(j+1<n?dcum[j+1]:dtotal)-dcum[j],t=(s-dcum[j])/(seg||1e-12);
    tx[k]=a[0]+(b[0]-a[0])*t;ty[k]=a[1]+(b[1]-a[1])*t;tz[k]=a[2]+(b[2]-a[2])*t;
  }
  for(let k=1;k<=m;k++){const j=k%m;tcum[k]=tcum[k-1]+Math.hypot(tx[j]-tx[k-1],ty[j]-ty[k-1]);}
  const tourLength=tcum[m],entries=T.entries,entryS=entries.map(e=>e.s);
  const spans=entries.map((e,i)=>({district:e.district,from:e.s,to:i+1<entries.length?entries[i+1].s:T.length}));
  const sampleOut={point:new THREE.Vector3(),tangent:new THREE.Vector3(),height:0,district:'core',index:0,s:0};
  // One point of the tour at arc length s (wraps): world point, unit world tangent (with the slope), deck
  // height, the district whose span holds s (a bridge belongs to the district it leaves) and the index
  // of the span. Pass `out` to keep the result; without it one shared object is reused (no allocation).
  function sample(s,out=sampleOut){
    s=((s%tourLength)+tourLength)%tourLength;
    let lo=0,hi=m;while(lo+1<hi){const mid=(lo+hi)>>1;if(tcum[mid]<=s)lo=mid;else hi=mid;}
    const j=(lo+1)%m,t=(s-tcum[lo])/(tcum[lo+1]-tcum[lo]||1e-12);
    const x=tx[lo]+(tx[j]-tx[lo])*t,y=ty[lo]+(ty[j]-ty[lo])*t,z=tz[lo]+(tz[j]-tz[lo])*t;
    out.point.set(x,z,-y);out.tangent.set(tx[j]-tx[lo],tz[j]-tz[lo],-(ty[j]-ty[lo])).normalize();
    out.height=z;out.s=s;
    let e=0,hiE=entryS.length;while(e+1<hiE){const mid=(e+hiE)>>1;if(entryS[mid]<=s)e=mid;else hiE=mid;}
    out.index=e;out.district=entries[e].district;
    return out;
  }
  const tour={length:tourLength,publishedLength:T.length,count:m,start:T.start,steps,legs:T.legs,entries,spans,
    archiveAvenue:T.archiveAvenue,sample,
    point(k,out=new THREE.Vector3()){k=((k%m)+m)%m;return out.set(tx[k],tz[k],-ty[k]);}};

  // surfaceAtRoad(x, z): the height of the paved surface (carriageway and sidewalks of a ring, avenue,
  // rim road, link or bridge deck, a junction corner, the pier, the island) at a world point, or null.
  // With several surfaces there (never on this layout: the design gates allow one walkable height per
  // plan point), it returns the one closest to `near`, or the highest.
  const CELL=2,segs=[],cells=new Map();
  const key=(i,j)=>i*65536+j;
  function addSeg(ax,ay,bx,by,za,zb,half){
    const k=segs.length/7;segs.push(ax,ay,bx,by,za,zb,half);
    for(let i=Math.floor((Math.min(ax,bx)-half)/CELL);i<=Math.floor((Math.max(ax,bx)+half)/CELL);i++)
      for(let j=Math.floor((Math.min(ay,by)-half)/CELL);j<=Math.floor((Math.max(ay,by)+half)/CELL);j++){
        const c=key(i,j);if(!cells.has(c))cells.set(c,[]);cells.get(c).push(k);}
  }
  D.routes.forEach(r=>{
    const half=(r.width||(r.district==='episodic'?.54:.88))/2+(r.sidewalk||.13);let pts=r.points,closed=true;
    if(r.shared){const c=cumulative(pts,false);pts=pts.filter((p,i)=>c[i]<=r.shared[0].from+1e-4);closed=false;}
    for(let i=0;i<pts.length-(closed?0:1);i++){const a=pts[i],b=pts[(i+1)%pts.length];addSeg(a[0],a[1],b[0],b[1],r.z,r.z,half);}
  });
  for(const st of D.streets||[])for(let i=0;i+1<st.points.length;i++){const a=st.points[i],b=st.points[i+1];addSeg(a[0],a[1],b[0],b[1],st.z,st.z,st.width/2+st.sidewalk);}
  for(const b of bridges)for(let i=0;i+1<b.points.length;i++){const p=b.points[i],q=b.points[i+1];addSeg(p[0],p[1],q[0],q[1],p[2],q[2],b.halfWidth);}
  const lake=D.lake&&D.lake[0];
  if(lake){const p=lake.pier;addSeg(p.x0,p.y0,p.x1,p.y1,p.z,p.z,p.width/2);}
  // Junction corners: the paved wedge between a ring's edge, the stub's edge and the fillet curb.
  const corners=[];
  for(const b of bridges)for(const e of b.ends)for(const f of e.fillets){
    const r=f.r-.13,lo=Math.min(f.a0,f.a1),span=Math.abs(f.a1-f.a0);
    corners.push({cx:f.cx,cy:f.cy,r,lo,span,z:e.z,reach:f.r+ROAD_HALF});
  }
  // Called every frame by later phases, so it allocates nothing.
  let best=null,nearH=0,hasNear=false;
  function take(h){if(best===null||(hasNear?Math.abs(h-nearH)<Math.abs(best-nearH):h>best))best=h;}
  function surfaceAtRoad(x,z,near){
    const px=x,py=-z,cell=cells.get(key(Math.floor(px/CELL),Math.floor(py/CELL)));
    best=null;hasNear=near!==undefined;nearH=hasNear?near:0;
    if(cell)for(let c=0;c<cell.length;c++){const o=cell[c]*7,ax=segs[o],ay=segs[o+1],dx=segs[o+2]-ax,dy=segs[o+3]-ay;
      const l2=dx*dx+dy*dy,t=l2?Math.max(0,Math.min(1,((px-ax)*dx+(py-ay)*dy)/l2)):0;
      if(Math.hypot(px-ax-dx*t,py-ay-dy*t)<=segs[o+6])take(segs[o+4]+(segs[o+5]-segs[o+4])*t);}
    for(let c=0;c<corners.length;c++){const k=corners[c],dx=px-k.cx,dy=py-k.cy,d=Math.hypot(dx,dy);
      if(d<k.r||d>k.reach)continue;
      const a=((Math.atan2(dy,dx)/RAD-k.lo)%360+360)%360;if(a<=k.span)take(k.z);}
    if(lake){const i=lake.island;if(Math.hypot(px-i.x,py-i.y)<=i.r)take(i.z);}
    return best;
  }

  // Temporary decks until V7 dresses the shore: the pier on four posts and the island base under the
  // Reef Island Stage. Plain and dark, one draw call, no light of their own.
  if(lake){
    const pos=[],colr=[],p=lake.pier,isl=lake.island,top=[.028,.034,.044],side=[.011,.013,.018];
    const quad=(a,b,c,d,shade)=>{for(const v of [a,b,c,a,c,d]){pos.push(...v);colr.push(...shade);}};
    const box=(x0,y0,x1,y1,w,zBot,zTop)=>{
      const ux=x1-x0,uy=y1-y0,l=Math.hypot(ux,uy)||1,nx=-uy/l*w/2,ny=ux/l*w/2;
      const c=[[x0+nx,y0+ny],[x1+nx,y1+ny],[x1-nx,y1-ny],[x0-nx,y0-ny]].map(q=>[q[0],q[1]]);
      const Wv=(q,h)=>[q[0],h,-q[1]];
      quad(Wv(c[0],zTop),Wv(c[3],zTop),Wv(c[2],zTop),Wv(c[1],zTop),top);
      for(let i=0;i<4;i++){const a=c[i],b=c[(i+1)%4];quad(Wv(a,zBot),Wv(b,zBot),Wv(b,zTop),Wv(a,zTop),side);}
    };
    box(p.x0,p.y0,p.x1,p.y1,p.width,p.z-.06,p.z);
    for(const t of [.2,.5,.8]){const x=p.x0+(p.x1-p.x0)*t,y=p.y0+(p.y1-p.y0)*t,ux=p.x1-p.x0,uy=p.y1-p.y0,l=Math.hypot(ux,uy);
      for(const s of [-1,1]){const cx=x-uy/l*s*.19,cy=y+ux/l*s*.19;box(cx-.03,cy,cx+.03,cy,.06,lake.z-.1,p.z-.06);}}
    const R=isl.r+.06,hBot=lake.z-.1,hTop=isl.z-.12,N=48;
    for(let k=0;k<N;k++){const a0=k/N*Math.PI*2,a1=(k+1)/N*Math.PI*2;
      const q0=[isl.x+Math.cos(a0)*R,isl.y+Math.sin(a0)*R],q1=[isl.x+Math.cos(a1)*R,isl.y+Math.sin(a1)*R];
      quad([q0[0],hBot,-q0[1]],[q1[0],hBot,-q1[1]],[q1[0],hTop,-q1[1]],[q0[0],hTop,-q0[1]],side);
      pos.push(isl.x,hTop,-isl.y,q1[0],hTop,-q1[1],q0[0],hTop,-q0[1]);colr.push(...top,...top,...top);}
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));g.setAttribute('color',new THREE.Float32BufferAttribute(colr,3));
    const decks=new THREE.Mesh(g,new THREE.MeshBasicMaterial({vertexColors:true,fog:true,side:THREE.DoubleSide}));
    decks.name='reef-temporary-decks';scene.add(decks);
  }
  const rim=D.routes.find(r=>r.kind==='rim')||null;
  return {graph,bridges,rim,lake:lake||null,streets:D.streets||[],tour,surfaceAtRoad,edgePoints,turnArc:arc};
})();

// ------------------------------------------------------------------ the bridges drawn (C6.3, C6.4, C6.5, C11.3)
// Scenery only (B1, B2). One merged deck mesh holds every bridge's carriageway (its lane markings are
// painted in its shader), sidewalks, fascia with the two edge light strips, underside glow and end caps,
// and the junction corners (the paved fillet and its curb sidewalk); a second mesh with the same shader
// holds the six Archive rim links. One merged mesh holds the neon guardrails, one instanced mesh the
// pylons and the cable-stay masts, one line set the stay cables, one band of static underglow on the void
// floor, then the bridge lamps and their pools, and one instanced mesh the crosswalk stripes of every
// junction (C11.3): nine draw calls.
// The light packets (C1.6) are the only reactive light here: attachLights() binds them to the beat and
// the Lights limiter once rave-light exists, and update() runs once a frame without allocating.
const bridgeScene=roadNet&&(()=>{
  const D=DATA.design,bridges=roadNet.bridges,RAD=Math.PI/180;
  const HALF=.44,EDGE=.57,WALK=.48,DECK=.14,TOP=.005,CURB=.77,FILLET=.9,INSET=.015;
  const lightOf=d=>lin(styleOf(d).light);
  const mixc=(a,b,t)=>[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t];
  const smooth01=t=>{t=Math.max(0,Math.min(1,t));return t*t*(3-2*t);};
  const skey=(i,j)=>i*65536+j;

  // A centreline as a track in layout coordinates: arc length, height, a unit tangent smoothed at the
  // vertices and its left normal. stations(a, b) lists a, every vertex between and b.
  function track(P){
    const n=P.length,cum=[0],tx=[],ty=[];
    for(let i=1;i<n;i++)cum.push(cum[i-1]+Math.hypot(P[i][0]-P[i-1][0],P[i][1]-P[i-1][1]));
    for(let i=0;i<n;i++){const a=P[Math.max(0,i-1)],b=P[Math.min(n-1,i+1)],l=Math.hypot(b[0]-a[0],b[1]-a[1])||1;tx.push((b[0]-a[0])/l);ty.push((b[1]-a[1])/l);}
    const L=cum[n-1];
    function at(s,o){
      s=Math.max(0,Math.min(L,s));let lo=0,hi=n-1;while(lo+1<hi){const m=(lo+hi)>>1;if(cum[m]<=s)lo=m;else hi=m;}
      const t=(s-cum[lo])/((cum[lo+1]-cum[lo])||1e-9),a=P[lo],b=P[lo+1];
      o.x=a[0]+(b[0]-a[0])*t;o.y=a[1]+(b[1]-a[1])*t;o.z=a[2]+(b[2]-a[2])*t;
      const x=tx[lo]+(tx[lo+1]-tx[lo])*t,y=ty[lo]+(ty[lo+1]-ty[lo])*t,l=Math.hypot(x,y)||1;
      o.tx=x/l;o.ty=y/l;o.nx=-o.ty;o.ny=o.tx;return o;
    }
    function stations(a,b){const s=[a];for(const c of cum)if(c>a+1e-6&&c<b-1e-6)s.push(c);s.push(b);return s;}
    return {P,cum,L,at,stations};
  }
  // Every ring is a circle except the Archive's avenues and its east rim road; half is its outer edge.
  const ringInfo=D.routes.map(r=>{
    let cx=0,cy=0,rMin=Infinity,rMax=0;for(const p of r.points){cx+=p[0];cy+=p[1];}cx/=r.points.length;cy/=r.points.length;
    for(const p of r.points){const d=Math.hypot(p[0]-cx,p[1]-cy);rMin=Math.min(rMin,d);rMax=Math.max(rMax,d);}
    const roadHalf=(r.width||(r.district==='episodic'?.54:.88))/2;
    return {route:D.routes.indexOf(r),disc:rMax-rMin<.02,cx,cy,R:(rMin+rMax)/2,z:r.z,district:r.district,roadHalf,half:roadHalf+(r.sidewalk||.13),
      points:r.points,own:r.shared?r.shared[0].from:null};
  });
  // Per bridge: its track, the stub distance where its carriageway leaves each ring's carriageway (on
  // a circle the kerb curves away, on the straight rim road it is the half width), the corner tangency
  // on the stub (bridgeS), where the stub's lane markings may start (cwA, cwB: just beyond the corners)
  // and the colour blend.
  const B=bridges.map((b,i)=>{
    const T=track(b.points),L=T.L,colA=lightOf(b.from),colB=lightOf(b.to);
    const bs=b.ends.map(e=>Math.max(...e.fillets.map(f=>f.bridgeS)));
    const s0=b.ends.map(e=>{const r=ringInfo[e.route];return r.disc?Math.sqrt((r.R+HALF)**2-HALF*HALF)-r.R:HALF;});
    const color=s=>mixc(colA,colB,smooth01((s-bs[0])/(L-bs[0]-bs[1])));
    return {b,i,T,L,colA,colB,bsA:bs[0],bsB:bs[1],s0,color,cwA:bs[0]+.17,cwB:L-bs[1]-.17,spoke:b.from==='core'};
  });
  const P3={x:0,y:0,z:0,tx:0,ty:0,nx:0,ny:0};

  // ---------------------------------------------------------------- the deck mesh
  // aPart: 0 carriageway, 1 sidewalk, 2 corner fillet (paved), 3 corner curb sidewalk, 4 fascia,
  // 5 underside, 6 end cap. aLoc: (lateral offset, arc length, road half width), or for the fascia
  // (side, arc length, depth below the top). aInfo: (bridge index, or -1 for a link and -2 for a corner,
  // length, marking start A, marking start B). aCenter: a corner's fillet centre in world x, z.
  let G={pos:[],part:[],loc:[],info:[],cen:[],colr:[],idx:[]},nv=0;
  function vert(x,y,h,part,l,info,cx,cy,c){G.pos.push(x,h,-y);G.part.push(part);G.loc.push(l[0],l[1],l[2]);G.info.push(info[0],info[1],info[2],info[3]);G.cen.push(cx,-cy);G.colr.push(c[0],c[1],c[2]);return nv++;}
  const quad=(a,b,c,d)=>G.idx.push(a,b,c,a,c,d);
  function band(T,info,s0,s1,part,m0,m1,dh0,dh1,locOf,colorOf){
    let pa=-1,pb=-1;
    for(const s of T.stations(s0,s1)){const p=T.at(s,P3),c=colorOf(s),x=p.x,y=p.y,z=p.z,nx=p.nx,ny=p.ny;
      const a=vert(x+nx*m0,y+ny*m0,z+dh0,part,locOf(m0,s,dh0),info,0,0,c),b=vert(x+nx*m1,y+ny*m1,z+dh1,part,locOf(m1,s,dh1),info,0,0,c);
      if(pa>=0)quad(pa,pb,b,a);pa=a;pb=b;}
  }
  for(const Q of B){
    const {T,L}=Q,info=[Q.i,L,Q.cwA,Q.cwB],col=Q.color,top=(m,s)=>[m,s,HALF];
    // The carriageway: on the flat stubs it reaches 0.012 into the fillet corners, and each sidewalk starts
    // 0.015 inside its curb sidewalk, so the seams between separately built pieces overlap (same material,
    // same height) and can never open a hairline crack onto the void.
    {let prev=null;const stubA=Q.bsA+.02,stubB=L-Q.bsB-.02;
      for(const s of T.stations(Q.s0[0],L-Q.s0[1])){const p=T.at(s,P3),c=col(s),w=s<stubA||s>stubB?HALF+.012:HALF,row=[];
        for(const m of [-w,-HALF,HALF,w])row.push(vert(p.x+p.nx*m,p.y+p.ny*m,p.z+TOP,0,[m,s,HALF],info,0,0,c));
        if(prev)for(let j=0;j<3;j++)quad(prev[j],prev[j+1],row[j+1],row[j]);prev=row;}}
    for(const side of [-1,1]){
      band(T,info,Q.bsA-.015,L-Q.bsB+.015,1,side*HALF,side*EDGE,TOP,TOP,top,col);
      band(T,info,Q.bsA,L-Q.bsB,4,side*EDGE,side*EDGE,TOP,-DECK,(m,s,dh)=>[side,s,dh-TOP],col);
    }
    band(T,info,Q.bsA,L-Q.bsB,5,-EDGE,EDGE,-DECK,-DECK,top,col);
    for(const s of [Q.bsA,L-Q.bsB]){const p=T.at(s,P3),c=col(s),v=[];
      for(const [m,dh] of [[-EDGE,TOP],[EDGE,TOP],[EDGE,-DECK],[-EDGE,-DECK]])v.push(vert(p.x+p.nx*m,p.y+p.ny*m,p.z+dh,6,[m,s,HALF],info,0,0,c));
      quad(v[0],v[1],v[2],v[3]);}
    // The junction corners: the paved fillet fanned from K, where the stub's kerb meets the ring's
    // kerb, out to the fillet arc, and the curb sidewalk between the arc and the curb's outer edge.
    Q.b.ends.forEach((e,k)=>{
      const c=lightOf(e.district),cinfo=[-2,0,0,0],p=T.at(k?L-Q.s0[1]:Q.s0[0],{}),h=e.z+TOP;
      for(const f of e.fillets){
        const K=vert(p.x+p.nx*f.side*HALF,p.y+p.ny*f.side*HALF,h,2,[0,0,0],cinfo,f.cx,f.cy,c);
        const n=Math.max(8,Math.ceil(Math.abs(f.a1-f.a0)*RAD*FILLET/.06));let pArc=-1,pIn=-1,pOut=-1;
        for(let j=0;j<=n;j++){const a=(f.a0+(f.a1-f.a0)*j/n)*RAD,ca=Math.cos(a),sa=Math.sin(a);
          const arc=vert(f.cx+ca*FILLET,f.cy+sa*FILLET,h,2,[0,0,0],cinfo,f.cx,f.cy,c);
          const vin=vert(f.cx+ca*CURB,f.cy+sa*CURB,h,3,[0,0,0],cinfo,f.cx,f.cy,c),vout=vert(f.cx+ca*FILLET,f.cy+sa*FILLET,h,3,[0,0,0],cinfo,f.cx,f.cy,c);
          if(j){G.idx.push(K,pArc,arc);quad(pIn,pOut,vout,vin);}
          pArc=arc;pIn=vin;pOut=vout;}
      }
    });
  }
  function toGeometry(){
    const g=new THREE.BufferGeometry();
    g.setAttribute('position',new THREE.Float32BufferAttribute(G.pos,3));g.setAttribute('aPart',new THREE.Float32BufferAttribute(G.part,1));
    g.setAttribute('aLoc',new THREE.Float32BufferAttribute(G.loc,3));g.setAttribute('aInfo',new THREE.Float32BufferAttribute(G.info,4));
    g.setAttribute('aCenter',new THREE.Float32BufferAttribute(G.cen,2));g.setAttribute('aColor',new THREE.Float32BufferAttribute(G.colr,3));
    g.setIndex(G.idx);g.computeBoundingSphere();G={pos:[],part:[],loc:[],info:[],cen:[],colr:[],idx:[]};nv=0;return g;
  }
  const deckGeo=toGeometry();
  // The six Archive rim links (C6.2) are forks, like the rim road: each leaves an avenue where its corner
  // starts and runs along the rim to the next avenue, overlapping both avenues at its ends. They sit 4 mm
  // under the avenues' asphalt (the through road wins the overlap, as at the rim road's forks) in their own
  // mesh without the deck's polygon offset.
  for(const st of D.streets||[]){
    const T=track(st.points.map(q=>[q[0],q[1],st.z])),L=T.L,half=st.width/2,walk=half+st.sidewalk,c=lightOf(st.district),info=[-1,L,-1,-1];
    const loc=(m,s)=>[m,s,half],col=()=>c;
    band(T,info,0,L,0,-half,half,.001,.001,loc,col);
    for(const side of [-1,1])band(T,info,0,L,1,side*half,side*walk,.001,.001,loc,col);
  }
  const linkGeo=toGeometry();
  // uPacket carries the whole limiter: the Lights level (its setting's amplitude, Calm 20 %, times the
  // 0.6 overview factor), the sound-off half and the cut; 0 under reduced motion (B9). uSlots and uLife
  // scale with the tier.
  const deckUniforms={uClock:{value:0},uPacket:{value:0},uSlots:{value:8},uLife:{value:8*60/140},uTint:{value:0},uColor:{value:new THREE.Color(1,1,1)},
    uKicks:{value:new Float32Array(8).fill(-100)},uGains:{value:new Float32Array(8)},uDir:{value:new Float32Array(16).fill(1)},
    uWalk:{value:col(hex('#263544'))},uMark:{value:col(hex('#b5b7a1'))}};
  const deckMat=new THREE.ShaderMaterial({fog:true,side:THREE.DoubleSide,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-4,
    uniforms:Object.assign(THREE.UniformsUtils.merge([THREE.UniformsLib.fog]),deckUniforms),
    vertexShader:`attribute float aPart;attribute vec3 aLoc,aColor;attribute vec4 aInfo;attribute vec2 aCenter;
      varying float vPart;varying vec3 vLoc,vColor,vWorld;varying vec4 vInfo;varying vec2 vCenter;
      #include <fog_pars_vertex>
      void main(){vPart=aPart;vLoc=aLoc;vColor=aColor;vInfo=aInfo;vCenter=aCenter;
        vec4 w=modelMatrix*vec4(position,1.0);vWorld=w.xyz;vec4 mvPosition=viewMatrix*w;gl_Position=projectionMatrix*mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader:`uniform float uClock,uPacket,uSlots,uLife,uTint;uniform vec3 uColor,uWalk,uMark;uniform float uKicks[8],uGains[8],uDir[16];
      varying float vPart;varying vec3 vLoc,vColor,vWorld;varying vec4 vInfo;varying vec2 vCenter;
      #include <fog_pars_fragment>
      float hash(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
      // The rings' wet asphalt (city-life.js), so a tee reads as one surface: across 0..1 over the carriageway.
      vec3 asphalt(float across,float along,vec2 cell){
        float grain=hash(floor(cell)),puddle=smoothstep(.2,.8,sin(along*3.1)*.5+.5);
        vec3 c=vec3(.008,.015,.025)*(.8+.2*grain)+vColor*pow(abs(across-.5)*2.0,2.8)*puddle*.11;
        return c+vec3(.026,.048,.057)*pow(max(0.0,1.0-abs(across-.43)*5.0),4.0)*puddle;
      }
      vec3 tiles(vec2 t){vec2 fw=max(fwidth(t),vec2(1e-4)),g=abs(fract(t-.5)-.5)/fw;float far=smoothstep(.25,.6,max(fw.x,fw.y));
        float joint=(1.0-min(min(g.x,g.y),1.0))*(1.0-far);return uWalk*mix(.92+.12*hash(floor(t)),.98,far)*(1.0-.4*joint);}
      float arrow(float a,float b){return max(step(-.15,a)*step(a,.04)*step(abs(b),.02),step(.04,a)*step(a,.15)*step(abs(b),.06*(1.0-(a-.04)/.11)));}
      // Light packets: one per kick, leaving the bridge end nearer the active room at 12 units/s.
      float packets(float s){
        if(uPacket<=0.0||vInfo.x<-.5)return 0.0;
        float x=uDir[int(vInfo.x+.5)]>0.0?s:vInfo.y-s,sum=0.0;
        for(int k=0;k<8;k++){if(float(k)>=uSlots)break;float age=uClock-uKicks[k];if(age<0.0||age>uLife)continue;
          // A comet: a sharp head and a short tail behind it.
          float d=x-age*12.0;sum+=(d>0.0?exp(-d*d*14.0):exp(d*1.4))*uGains[k]*(1.0-age/uLife);}
        return sum*uPacket;
      }
      vec3 packetColor(){return mix(vColor,uColor,.55);}
      vec3 strip(float s,float p){return vColor*.62+uColor*.12*uTint+packetColor()*2.6*p;}
      void main(){
        vec3 c;vec3 V=normalize(cameraPosition-vWorld);float fres=pow(1.0-clamp(V.y,0.0,1.0),5.0);
        if(vPart<.5){
          float m=vLoc.x,s=vLoc.y,hw=vLoc.z,across=m/(2.0*hw)+.5,paint=0.0;
          c=asphalt(across,s,vec2(across*320.0,s*140.0))+vColor*.06*fres;
          bool bridge=vInfo.x>-.5;
          float lo=bridge?vInfo.z+.15:hw+.13,hi=bridge?vInfo.w-.15:vInfo.y-hw-.13;
          if(s>lo&&s<hi){
            paint=step(abs(m),.0125)*step(abs(mod(s-lo,1.8)-.9),.16);
            if(bridge){float sc=lo+3.6+floor((s-lo)/7.2)*7.2;
              if(sc+.3<hi)paint=max(paint,max(arrow(s-sc,m+.14),arrow(sc-s,m-.14)));}
          }
          c=mix(c,uMark,min(1.0,paint*.38));
        } else if(vPart<1.5){
          float m=abs(vLoc.x),s=vLoc.y,kerb=m-vLoc.z;
          c=tiles(vec2(m,s)/.065);c=mix(c,vColor,.42*step(.016,kerb)*step(kerb,.034));
          if(vInfo.x>-.5){float fw=fwidth(m)*1.5;c=mix(c,strip(s,packets(s)),smoothstep(.556-max(.008,fw),.556,m));}
        } else if(vPart<2.5){
          float d=length(vWorld.xz-vCenter),across=clamp((d-.9)/.88,0.0,1.0);
          c=asphalt(across,vWorld.x+vWorld.z,vWorld.xz*140.0)+vColor*.06*fres;
        } else if(vPart<3.5){
          float kerb=.9-length(vWorld.xz-vCenter);
          c=tiles(vWorld.xz/.065);c=mix(c,vColor,.42*step(.016,kerb)*step(kerb,.034));
        } else if(vPart<4.5){
          float h=vLoc.z,s=vLoc.y;
          c=vec3(.016,.02,.028);
          float fh=max(0.0,fwidth(h)*1.5-.035),p=packets(s);c=mix(c,strip(s,p),step(-.055-fh,h)*step(h,-.02));
          c+=packetColor()*p*.9*exp(-abs(h+.037)*18.0);
          c=mix(c,vColor*.3,step(-.118,h)*step(h,-.108));
        } else if(vPart<5.5){
          float m=abs(vLoc.x)/.57;c=vec3(.012,.015,.02)+vColor*(.05+.2*(1.0-m)*(1.0-m));
        } else c=vec3(.014,.017,.024);
        gl_FragColor=vec4(c,1.0);
        #include <fog_fragment>
        #include <colorspace_fragment>
      }`});
  const deck=new THREE.Mesh(deckGeo,deckMat);deck.name='bridge-decks';scene.add(deck);
  const linkMat=deckMat.clone();linkMat.polygonOffset=false;
  const links=new THREE.Mesh(linkGeo,linkMat);links.name='archive-rim-links';scene.add(links);
  // The underside's light spilling onto the void: a soft static band in the blended colours just above the
  // grid floor (0.05 over it, so the two never z-fight) under each span, additive and fading to nothing 1.6
  // out, so each bridge reads from the overview.
  const GP=[],GC=[],GI=[];let gn=0;
  for(const Q of B){const {T,L}=Q;let prev=null;
    for(const s of T.stations(Q.bsA,L-Q.bsB)){const p=T.at(s,P3),c=Q.color(s),k=.13*smooth01(Math.min(s-Q.bsA,L-Q.bsB-s)/1.5),row=[];
      for(const [m,w] of [[-1.6,0],[-.35,k],[.35,k],[1.6,0]]){GP.push(p.x+p.nx*m,.03,-(p.y+p.ny*m));GC.push(c[0]*w,c[1]*w,c[2]*w);row.push(gn++);}
      if(prev)for(let j=0;j<3;j++)GI.push(prev[j],row[j],row[j+1],prev[j],row[j+1],prev[j+1]);prev=row;}}
  const glowGeo=new THREE.BufferGeometry();glowGeo.setAttribute('position',new THREE.Float32BufferAttribute(GP,3));glowGeo.setAttribute('color',new THREE.Float32BufferAttribute(GC,3));glowGeo.setIndex(GI);glowGeo.computeBoundingSphere();
  const underglow=new THREE.Mesh(glowGeo,new THREE.MeshBasicMaterial({vertexColors:true,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true,fog:true}));
  underglow.name='bridge-underglow';scene.add(underglow);

  // ---------------------------------------------------------------- walkable surfaces as shapes
  // Used by the rails (C6.5) and the pylon clearances. gap(x, y) is the plan distance to the surface
  // (negative inside); h(x, y) its height there.
  const TOL=.03,SH=[],shGrid=new Map(),SC=4;
  function addShape(sh,x0,y0,x1,y1){sh.id=SH.length;SH.push(sh);
    for(let i=Math.floor(x0/SC);i<=Math.floor(x1/SC);i++)for(let j=Math.floor(y0/SC);j<=Math.floor(y1/SC);j++){const k=skey(i,j);if(!shGrid.has(k))shGrid.set(k,[]);shGrid.get(k).push(sh);}
    return sh;}
  function polyGrid(P,closed){const cells=new Map(),n=P.length,m=closed?n:n-1;
    for(let k=0;k<m;k++){const a=P[k],b=P[(k+1)%n];
      for(let i=Math.floor((Math.min(a[0],b[0])-1.2)/2);i<=Math.floor((Math.max(a[0],b[0])+1.2)/2);i++)
        for(let j=Math.floor((Math.min(a[1],b[1])-1.2)/2);j<=Math.floor((Math.max(a[1],b[1])+1.2)/2);j++){const c=skey(i,j);if(!cells.has(c))cells.set(c,[]);cells.get(c).push(k);}}
    return {P,n,cells};}
  const NEAR={d:0,t:0,k:-1,cross:0};
  function nearest(g,x,y){NEAR.d=Infinity;NEAR.k=-1;const cell=g.cells.get(skey(Math.floor(x/2),Math.floor(y/2)));if(!cell)return NEAR;
    for(const k of cell){const a=g.P[k],b=g.P[(k+1)%g.n],dx=b[0]-a[0],dy=b[1]-a[1],l2=dx*dx+dy*dy,t=l2?Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/l2)):0,d=Math.hypot(x-a[0]-dx*t,y-a[1]-dy*t);
      if(d<NEAR.d){NEAR.d=d;NEAR.t=t;NEAR.k=k;NEAR.cross=dx*(y-a[1])-dy*(x-a[0]);}}
    return NEAR;}
  function inPolygon(P,x,y){let inside=false;for(let i=0,j=P.length-1;i<P.length;j=i++){const a=P[i],b=P[j];if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])inside=!inside;}return inside;}
  const bboxOf=P=>{let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;for(const p of P){x0=Math.min(x0,p[0]);y0=Math.min(y0,p[1]);x1=Math.max(x1,p[0]);y1=Math.max(y1,p[1]);}return [x0-1.4,y0-1.4,x1+1.4,y1+1.4];};
  const plateauShape={},loopShape=[],bandShape=[],wedgeShapes=[];
  for(const [d,p] of Object.entries(DATA.plateaus)){
    if(p.shape==='disc')plateauShape[d]=addShape({kind:'plateau',district:d,gap:(x,y)=>Math.hypot(x-p.cx,y-p.cy)-p.rx,h:()=>p.z},p.cx-p.rx-1,p.cy-p.rx-1,p.cx+p.rx+1,p.cy+p.rx+1);
    else{const r=2.5,ax=p.rx-r,ay=p.ry-r;
      plateauShape[d]=addShape({kind:'plateau',district:d,gap:(x,y)=>{const qx=Math.abs(x-p.cx)-ax,qy=Math.abs(y-p.cy)-ay;return Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0)-r;},h:()=>p.z},
        p.cx-p.rx-1,p.cy-p.ry-1,p.cx+p.rx+1,p.cy+p.ry+1);}
  }
  D.routes.forEach((r,ri)=>{const R=ringInfo[ri],half=R.half;
    if(R.disc)loopShape[ri]=addShape({kind:'loop',district:r.district,route:ri,gap:(x,y)=>Math.hypot(x-R.cx,y-R.cy)-R.R-half,h:()=>r.z},R.cx-R.R-1.4,R.cy-R.R-1.4,R.cx+R.R+1.4,R.cy+R.R+1.4);
    else{const g=polyGrid(r.points,true);
      loopShape[ri]=addShape({kind:'loop',district:r.district,route:ri,h:()=>r.z,gap:(x,y)=>{const q=nearest(g,x,y);
        if(q.k<0)return inPolygon(r.points,x,y)?-1.2:1.2;return q.cross>0?-q.d-half:q.d-half;}},...bboxOf(r.points));}
  });
  B.forEach(Q=>{const P=Q.b.points,g=polyGrid(P,false);
    bandShape[Q.i]=addShape({kind:'bridge',bridge:Q.i,gap:(x,y)=>{const q=nearest(g,x,y);return q.k<0?1.2:q.d-EDGE;},
      h:(x,y)=>{const q=nearest(g,x,y);if(q.k<0)return -9;const a=P[q.k],b=P[q.k+1];return a[2]+(b[2]-a[2])*q.t;}},...bboxOf(P));});
  const linkShapes=[];
  for(const st of D.streets||[]){const g=polyGrid(st.points,false),half=st.width/2+st.sidewalk;
    linkShapes.push(addShape({kind:'link',gap:(x,y)=>{const q=nearest(g,x,y);return q.k<0?1.2:q.d-half;},h:()=>st.z},...bboxOf(st.points)));}
  // A fillet corner: the paved wedge between the curb's outer edge and the two centrelines.
  B.forEach(Q=>Q.b.ends.forEach(e=>e.fillets.forEach(f=>{const span=f.a1-f.a0;
    wedgeShapes.push(addShape({kind:'corner',district:e.district,wedge:true,h:()=>e.z,gap:(x,y)=>{const dx=x-f.cx,dy=y-f.cy,d=Math.hypot(dx,dy),u=(((Math.atan2(dy,dx)/RAD-f.a0)%360+540)%360-180)/span;
      return u>0&&u<1&&d<1.34?CURB-d:1;}},f.cx-1.4,f.cy-1.4,f.cx+1.4,f.cy+1.4));})));
  const decks=(D.stages||[]).filter(s=>s.kind==='deck');
  const lake=roadNet.lake,pier=lake&&lake.pier;
  const shore=lake?Array.from({length:180},(_,i)=>{const t=i/180*Math.PI*2,ca=Math.cos(lake.angle),sa=Math.sin(lake.angle),u=Math.cos(t)*lake.rx,v=Math.sin(t)*lake.ry;return [lake.cx+u*ca-v*sa,lake.cy+u*sa+v*ca];}):[];
  const shoreGap=(x,y)=>{let d=Infinity;for(const p of shore)d=Math.min(d,Math.hypot(x-p[0],y-p[1]));return d;};
  function segGap(x,y,ax,ay,bx,by){const dx=bx-ax,dy=by-ay,l2=dx*dx+dy*dy,t=l2?Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/l2)):0;return Math.hypot(x-ax-dx*t,y-ay-dy*t);}

  // ---------------------------------------------------------------- rails (C6.5)
  // The walkable city is the union of the plateaus, the ring loops filled out to their outer sidewalk
  // edge, the links, the bridge decks and the fillet corners. A low neon rail runs along that union's
  // boundary, so it follows every rim, wraps each junction corner onto its bridge and runs along both
  // bridge edges. It stays open where a stage deck meets a ring (a gap under 0.25) and along the Reef's
  // lake shore (within 1.6 of the lake: V7 opens it onto the beach). Each boundary is sampled every
  // 0.25 or less; a sample is dropped when another surface at its own height covers it, and every cut
  // is bisected so two rails meeting at a corner join.
  function covered(x,y,h,own,reef){
    const cell=shGrid.get(skey(Math.floor(x/SC),Math.floor(y/SC)));
    if(cell)for(const sh of cell){if(sh===own||Math.abs(sh.h(x,y)-h)>.25)continue;if(sh.gap(x,y)<(sh.wedge?-.005:-TOL))return true;}
    for(const s of decks)if(Math.abs(s.z-h)<.3&&Math.hypot(x-s.x,y-s.y)-s.r<.25)return true;
    if(pier&&Math.abs(pier.z-h)<.3&&segGap(x,y,pier.x0,pier.y0,pier.x1,pier.y1)<pier.width/2+.2)return true;
    return reef&&shoreGap(x,y)<1.6;
  }
  const railRuns=[];
  // samples: [x, y, h, colour] along one boundary; own: the shape it bounds.
  function boundary(samples,closed,own,kind,reef){
    const n=samples.length,keep=samples.map(p=>!covered(p[0],p[1],p[2],own,reef));
    const edgeAt=(a,b)=>{let lo=0,hi=1;for(let i=0;i<14;i++){const m=(lo+hi)/2;if(covered(a[0]+(b[0]-a[0])*m,a[1]+(b[1]-a[1])*m,a[2]+(b[2]-a[2])*m,own,reef))hi=m;else lo=m;}
      return [a[0]+(b[0]-a[0])*lo,a[1]+(b[1]-a[1])*lo,a[2]+(b[2]-a[2])*lo,a[3]];};
    if(closed&&keep.every(Boolean)){railRuns.push({kind,points:samples.concat([samples[0]]),closed:true});return;}
    const start=closed?keep.indexOf(false):0;let run=null;
    for(let k=0;k<n;k++){const i=(start+k)%n;
      if(keep[i]){if(!run){run=[];const prev=i>0?i-1:closed?n-1:-1;if(prev>=0)run.push(edgeAt(samples[i],samples[prev]));}run.push(samples[i]);}
      else if(run){run.push(edgeAt(samples[(i-1+n)%n],samples[i]));if(run.length>1)railRuns.push({kind,points:run});run=null;}
    }
    if(run){if(closed)run.push(edgeAt(samples[(start-1+n)%n],samples[start]));if(run.length>1)railRuns.push({kind,points:run});}
  }
  const circle=(cx,cy,r,h,c,step=.25)=>{const n=Math.max(24,Math.ceil(2*Math.PI*r/step));return Array.from({length:n},(_,i)=>{const a=i/n*2*Math.PI;return [cx+Math.cos(a)*r,cy+Math.sin(a)*r,h,c];});};
  for(const [d,p] of Object.entries(DATA.plateaus)){const c=lightOf(d),sh=plateauShape[d];
    if(p.shape==='disc'){boundary(circle(p.cx,p.cy,p.rx-INSET,p.z,c),true,sh,'rim',d==='reef');continue;}
    const r=2.5-INSET,ax=p.rx-2.5,ay=p.ry-2.5,X=p.rx-INSET,Y=p.ry-INSET,pts=[];
    const corner=(cx,cy,a0)=>{for(let j=0;j<12;j++){const a=(a0+j/12*90)*RAD;pts.push([cx+Math.cos(a)*r,cy+Math.sin(a)*r,p.z,c]);}};
    const edge=(x0,y0,x1,y1)=>{const n=Math.ceil(Math.hypot(x1-x0,y1-y0)/.25);for(let j=0;j<n;j++)pts.push([x0+(x1-x0)*j/n,y0+(y1-y0)*j/n,p.z,c]);};
    edge(p.cx-ax,p.cy-Y,p.cx+ax,p.cy-Y);corner(p.cx+ax,p.cy-ay,-90);edge(p.cx+X,p.cy-ay,p.cx+X,p.cy+ay);corner(p.cx+ax,p.cy+ay,0);
    edge(p.cx+ax,p.cy+Y,p.cx-ax,p.cy+Y);corner(p.cx-ax,p.cy+ay,90);edge(p.cx-X,p.cy+ay,p.cx-X,p.cy-ay);corner(p.cx-ax,p.cy-ay,180);
    boundary(pts,true,sh,'rim',false);
  }
  D.routes.forEach((r,ri)=>{const R=ringInfo[ri],c=lightOf(r.district),sh=loopShape[ri],reef=r.district==='reef';
    if(R.disc){boundary(circle(R.cx,R.cy,R.R+R.half-INSET,r.z,c),true,sh,'rim',reef);return;}
    const P=r.points,n=P.length,o=R.half-INSET,pts=[];
    for(let i=0;i<n;i++){const a=P[(i-1+n)%n],b=P[(i+1)%n],l=Math.hypot(b[0]-a[0],b[1]-a[1])||1;pts.push([P[i][0]+(b[1]-a[1])/l*o,P[i][1]-(b[0]-a[0])/l*o,r.z,c]);}
    boundary(pts,true,sh,'rim',reef);
  });
  for(const Q of B){const {T,L}=Q;
    for(const side of [-1,1]){const pts=[];for(const s of T.stations(0,L)){const p=T.at(s,P3),o=side*(EDGE-INSET);pts.push([p.x+p.nx*o,p.y+p.ny*o,p.z,Q.color(s)]);}
      boundary(pts,false,bandShape[Q.i],'bridge',false);}}
  (D.streets||[]).forEach((st,k)=>{const T=track(st.points.map(q=>[q[0],q[1],st.z])),c=lightOf(st.district),o=st.width/2+st.sidewalk-INSET;
    for(const side of [-1,1]){const pts=[];for(const s of T.stations(0,T.L)){const p=T.at(s,P3);pts.push([p.x+p.nx*side*o,p.y+p.ny*side*o,st.z,c]);}
      boundary(pts,false,linkShapes[k],'rim',false);}});
  {let w=0;B.forEach(Q=>Q.b.ends.forEach(e=>e.fillets.forEach(f=>{const sh=wedgeShapes[w++],c=lightOf(e.district),n=Math.max(6,Math.ceil(Math.abs(f.a1-f.a0)*RAD*CURB/.1)),pts=[];
    for(let j=0;j<=n;j++){const a=(f.a0+(f.a1-f.a0)*j/n)*RAD;pts.push([f.cx+Math.cos(a)*(CURB+INSET),f.cy+Math.sin(a)*(CURB+INSET),e.z,c]);}
    boundary(pts,false,sh,'corner',e.district==='reef');})));}
  // Rail geometry: a neon top rail (a vertical band and a cap), a dim mid rail and dark posts every 0.6.
  const RP=[],RC=[],RI=[];let rn=0;
  const rv=(x,y,h,c)=>{RP.push(x,h,-y);RC.push(c[0],c[1],c[2]);return rn++;};
  const POST=[.018,.022,.03],rq=(a,b,c,d)=>RI.push(a,b,c,a,c,d);
  for(const run of railRuns){const pts=run.points;let prev=null,dist=0,nextPost=0;
    for(let i=0;i<pts.length;i++){const p=pts[i],x=p[0],y=p[1],h=p[2],c=p[3],glow=[c[0]*.85,c[1]*.85,c[2]*.85],dim=[c[0]*.22,c[1]*.22,c[2]*.22];
      const a=pts[Math.max(0,i-1)],b=pts[Math.min(pts.length-1,i+1)],l=Math.hypot(b[0]-a[0],b[1]-a[1])||1,nx=-(b[1]-a[1])/l*.005,ny=(b[0]-a[0])/l*.005;
      const v=[rv(x,y,h+.108,glow),rv(x,y,h+.12,glow),rv(x+nx,y+ny,h+.12,glow),rv(x-nx,y-ny,h+.12,glow),rv(x,y,h+.055,dim),rv(x,y,h+.061,dim)];
      if(prev){rq(prev[0],v[0],v[1],prev[1]);rq(prev[2],v[2],v[3],prev[3]);rq(prev[4],v[4],v[5],prev[5]);dist+=Math.hypot(x-pts[i-1][0],y-pts[i-1][1]);}
      prev=v;
      if(dist>=nextPost||i===pts.length-1){nextPost=dist+.6;const q=.009,cs=[[x-q,y-q],[x+q,y-q],[x+q,y+q],[x-q,y+q]];
        for(let k=0;k<4;k++){const u=cs[k],w=cs[(k+1)%4];rq(rv(u[0],u[1],h,POST),rv(w[0],w[1],h,POST),rv(w[0],w[1],h+.108,POST),rv(u[0],u[1],h+.108,POST));}}
    }
  }
  const railGeo=new THREE.BufferGeometry();railGeo.setAttribute('position',new THREE.Float32BufferAttribute(RP,3));railGeo.setAttribute('color',new THREE.Float32BufferAttribute(RC,3));railGeo.setIndex(RI);railGeo.computeBoundingSphere();
  const rails=new THREE.Mesh(railGeo,new THREE.MeshBasicMaterial({vertexColors:true,side:THREE.DoubleSide,fog:true}));rails.name='rails';scene.add(rails);

  // ---------------------------------------------------------------- pylons and the cable-stayed spokes
  // A pylon stands wherever the deck crosses open void, about every 5 units and at least 1 unit from
  // the corners, clear of every other surface by 0.3 in plan (so never on a ring below an overpass).
  // Each Compass spoke gets one H-frame of two masts near its midpoint with neon stay cables fanning
  // to both deck edges; the Memory Causeway's is the tallest.
  const clearAt=(x,y,own,m)=>{const cell=shGrid.get(skey(Math.floor(x/SC),Math.floor(y/SC)));
    if(cell)for(const sh of cell){if(sh===own||sh.wedge)continue;if(sh.gap(x,y)<m)return false;}
    for(const s of decks)if(Math.hypot(x-s.x,y-s.y)-s.r<m)return false;
    if(lake){const ca=Math.cos(-lake.angle),sa=Math.sin(-lake.angle),u=(x-lake.cx)*ca-(y-lake.cy)*sa,v=(x-lake.cx)*sa+(y-lake.cy)*ca;if((u/(lake.rx+m))**2+(v/(lake.ry+m))**2<1)return false;}
    return true;};
  const pylonRows=[],cableP=[],cableC=[],masts=[];
  const box=(x,y,y0,y1,yaw,w,d,c,line)=>pylonRows.push({x,y,y0,y1,yaw,w,d,c,line});
  for(const Q of B){const {T,L}=Q,own=bandShape[Q.i];let mastS=-1;
    if(Q.spoke){const H=Math.min(3.6,Math.max(2.2,.11*L)),lat=.66;
      for(let k=0;k<=Math.ceil(.15*L/.2)&&mastS<0;k++)for(const sg of k?[1,-1]:[1]){const s=L/2+sg*k*.2,p=T.at(s,P3);
        if(clearAt(p.x+p.nx*lat,p.y+p.ny*lat,own,.3)&&clearAt(p.x-p.nx*lat,p.y-p.ny*lat,own,.3)){mastS=s;break;}}
      if(mastS>=0){const p=T.at(mastS,{}),c=Q.color(mastS),yaw=Math.atan2(p.ny,p.nx),top=p.z+H;
        for(const side of [-1,1]){const x=p.x+p.nx*side*lat,y=p.y+p.ny*side*lat;box(x,y,-.02,top,yaw,.12,.12,c,1);masts.push({x,y,top,s:mastS,bridge:Q.i});}
        box(p.x,p.y,top-.14,top-.06,yaw,1.44,.1,c,0);box(p.x,p.y,p.z-DECK-.1,p.z-DECK,yaw,1.44,.12,c,0);
        const reach=Math.min(mastS-Q.bsA-.8,L-Q.bsB-.8-mastS,H*2.2);
        for(const side of [-1,1])for(const dir of [-1,1])for(let j=0;j<4;j++){
          const s=mastS+dir*(1.1+j*(reach-1.1)/3),q=T.at(s,{}),cq=Q.color(s),h=p.z+H*(.62+.1*j),ax=p.x+p.nx*side*lat,ay=p.y+p.ny*side*lat;
          cableP.push(ax,h,-ay,q.x+q.nx*side*EDGE,q.z+.02,-(q.y+q.ny*side*EDGE));cableC.push(c[0]*.75,c[1]*.75,c[2]*.75,cq[0]*.75,cq[1]*.75,cq[2]*.75);}
      }
    }
    const a=Q.bsA+1,b=L-Q.bsB-1,len=b-a;if(len<0)continue;
    const n=Math.max(1,Math.round(len/5));
    for(let k=0;k<n;k++){const s=a+(k+.5)*len/n;if(mastS>=0&&Math.abs(s-mastS)<2.5)continue;
      for(const off of [0,.4,-.4,.8,-.8]){if(s+off<a||s+off>b)continue;const q=T.at(s+off,P3);
        if(clearAt(q.x,q.y,own,.3)){box(q.x,q.y,-.02,q.z-DECK,Math.atan2(q.ny,q.nx),.16,.1,Q.color(s+off),1);break;}}}
  }
  const pylonGeo=new THREE.BoxGeometry(1,1,1).translate(0,.5,0);
  pylonGeo.setAttribute('aLine',new THREE.InstancedBufferAttribute(new Float32Array(Math.max(1,pylonRows.length)).map((v,i)=>pylonRows[i]?pylonRows[i].line:0),1));
  const pylonMat=new THREE.ShaderMaterial({fog:true,uniforms:THREE.UniformsUtils.merge([THREE.UniformsLib.fog,{uKey:{value:KEY}}]),
    vertexShader:`attribute float aLine;varying vec3 vObj,vN,vColor;varying float vLine;
      #include <fog_pars_vertex>
      void main(){vObj=position;vN=normalize(mat3(modelMatrix)*mat3(instanceMatrix)*normal);vColor=instanceColor;vLine=aLine;
        vec4 mvPosition=modelViewMatrix*instanceMatrix*vec4(position,1.0);gl_Position=projectionMatrix*mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader:`uniform vec3 uKey;varying vec3 vObj,vN,vColor;varying float vLine;
      #include <fog_pars_fragment>
      void main(){float d=max(dot(normalize(vN),uKey),0.0);vec3 c=vec3(.02,.025,.034)*(.55+.45*d);
        // A thin vertical light line down each face that looks across the bridge (object x).
        float line=vLine*step(.45,abs(vObj.x))*(1.0-smoothstep(.07,.12,abs(vObj.z)));
        gl_FragColor=vec4(mix(c,vColor*1.3,line),1.0);
        #include <fog_fragment>
        #include <colorspace_fragment>
      }`});
  const pylons=new THREE.InstancedMesh(pylonGeo,pylonMat,Math.max(1,pylonRows.length));pylons.name='bridge-pylons';
  {const d=new THREE.Object3D(),c=new THREE.Color();pylonRows.forEach((r,i)=>{d.position.set(r.x,r.y0,-r.y);d.rotation.set(0,r.yaw,0);d.scale.set(r.w,Math.max(.001,r.y1-r.y0),r.d);d.updateMatrix();
    pylons.setMatrixAt(i,d.matrix);pylons.setColorAt(i,c.setRGB(r.c[0],r.c[1],r.c[2]));});}
  pylons.count=pylonRows.length;pylons.frustumCulled=false;scene.add(pylons);
  const cableGeo=new THREE.BufferGeometry();cableGeo.setAttribute('position',new THREE.Float32BufferAttribute(cableP,3));cableGeo.setAttribute('color',new THREE.Float32BufferAttribute(cableC,3));
  const cables=new THREE.LineSegments(cableGeo,new THREE.LineBasicMaterial({vertexColors:true,fog:true}));cables.name='stay-cables';scene.add(cables);

  // ---------------------------------------------------------------- lamps (city-life.js's rule)
  // From 1.5 every 3.8 on the left of the bridge's from-to direction (the rule's offset side), at
  // width/2 + 0.07 on the sidewalk; none inside a ring's carriageway or a junction mouth, none within 1
  // of a street lamp already there or 0.5 of a mast. Each lamp takes the colour of the nearer district.
  const bridgeRoutes=B.map(Q=>{const pts=Q.b.points.map(q=>W(q[0],q[1],q[2])),lengths=[0];
    for(let i=1;i<pts.length;i++)lengths.push(lengths[i-1]+pts[i-1].distanceTo(pts[i]));
    return {name:Q.b.name,district:Q.b.from,points:pts,lengths,length:lengths[lengths.length-1],open:true,width:.88,bridge:Q.i};});
  const bridgeLampSpots=[];
  bridgeRoutes.forEach((route,i)=>{const Q=B[i];
    for(let d=1.5;d<route.length;d+=3.8){const p=sampleRoute(route,d,new THREE.Vector3(),route.width/2+.07);
      if(inOtherCarriageway(p,-1,.06)||lifeLamps.some(l=>l.p.distanceTo(p)<1)||masts.some(m=>Math.hypot(m.x-p.x,m.y+p.z)<.5))continue;
      bridgeLampSpots.push({p,district:d<route.length/2?Q.b.from:Q.b.to,bridge:i,d});}});
  const bridgeLamps=instanced('lamp',Math.max(1,bridgeLampSpots.length));
  bridgeLampSpots.forEach((s,k)=>staticSet(bridgeLamps,k,s.p,[.85,1.05,.85],0,MATTE,styleOf(s.district).light,.37+k*.13));
  bridgeLamps.mesh.count=bridgeLampSpots.length;bridgeLamps.mesh.instanceMatrix.needsUpdate=true;bridgeLamps.mesh.name='bridge-lamps';
  const lampPools=new THREE.InstancedMesh(pavementPools.geometry,pavementPools.material,Math.max(1,bridgeLampSpots.length));
  bridgeLampSpots.forEach((s,k)=>{dummy.position.copy(s.p);dummy.position.y+=.025;dummy.rotation.set(-Math.PI/2,0,0);dummy.scale.set(1,1,1);dummy.updateMatrix();lampPools.setMatrixAt(k,dummy.matrix);lampPools.setColorAt(k,col(styleOf(s.district).light));});
  lampPools.count=bridgeLampSpots.length;lampPools.name='bridge-lamp-pools';streetGroup.add(lampPools);

  // ---------------------------------------------------------------- walkers' bridge paths (C3.4)
  // Per bridge and side: a stretch of the ring's outer walking line (0.48 out, like every ring walker)
  // toward the junction, round the fillet corner 0.04 inside its kerb, along the bridge sidewalk 0.48
  // from the centreline, round the far corner and along the far ring's walking line away from it. A
  // ring stretch stops short of the next junction on that ring and of an open road's ends. A walker
  // folds back at either end, like a walker on the open rim road.
  const junctions=new Map();
  B.forEach(Q=>Q.b.ends.forEach(e=>{const s=e.fillets.map(f=>f.ringS);if(!junctions.has(e.route))junctions.set(e.route,[]);junctions.get(e.route).push([Math.min(...s),Math.max(...s)]);}));
  function ringStretch(e,f,len){
    const r=D.routes[e.route],own=r.shared?r.shared[0].from:null,P=r.points,n=P.length,cum=[0];
    for(let i=1;i<=n;i++)cum.push(cum[i-1]+Math.hypot(P[i%n][0]-P[i-1][0],P[i%n][1]-P[i-1][1]));
    const total=cum[n],wrap=v=>own===null?((v%total)+total)%total:v;
    let rel=f.ringS-e.s;if(own===null)rel=((rel%total)+total*1.5)%total-total/2;const dir=rel>0?1:-1;
    for(const [a,b] of junctions.get(e.route)){let gap=((dir>0?a:b)-f.ringS)*dir;if(own===null)gap=((gap%total)+total)%total;if(gap>.2&&gap<len+.3)len=gap-.3;}
    if(own!==null)len=Math.min(len,dir>0?own-.3-f.ringS:f.ringS-.3);
    const out=[],steps=Math.max(2,Math.ceil(len/.2));
    for(let j=steps;j>=0;j--){const s=wrap(f.ringS+dir*len*j/steps);let lo=0,hi=n;while(lo+1<hi){const m=(lo+hi)>>1;if(cum[m]<=s)lo=m;else hi=m;}
      const a=P[lo],b=P[(lo+1)%n],t=(s-cum[lo])/((cum[lo+1]-cum[lo])||1e-9),l=Math.hypot(b[0]-a[0],b[1]-a[1])||1;
      out.push([a[0]+(b[0]-a[0])*t+(b[1]-a[1])/l*WALK,a[1]+(b[1]-a[1])*t-(b[0]-a[0])/l*WALK,r.z]);}
    return out;
  }
  const walkPaths=[];
  for(const Q of B){const {T,L,b}=Q;
    for(const side of [1,-1]){
      const fA=b.ends[0].fillets.find(f=>f.side===side),fB=b.ends[1].fillets.find(f=>f.side===side),pts=[];
      const corner=(e,f,rev)=>{const n=Math.max(6,Math.ceil(Math.abs(f.a1-f.a0)*RAD*(FILLET-.04)/.1)),o=[];
        for(let j=0;j<=n;j++){const a=(f.a0+(f.a1-f.a0)*j/n)*RAD;o.push([f.cx+Math.cos(a)*(FILLET-.04),f.cy+Math.sin(a)*(FILLET-.04),e.z]);}return rev?o.reverse():o;};
      pts.push(...ringStretch(b.ends[0],fA,2.5),...corner(b.ends[0],fA,false));
      for(const s of T.stations(Q.bsA,L-Q.bsB)){const p=T.at(s,P3);pts.push([p.x+p.nx*side*WALK,p.y+p.ny*side*WALK,p.z]);}
      pts.push(...corner(b.ends[1],fB,true),...ringStretch(b.ends[1],fB,2.5).reverse());
      const points=[],lengths=[0];for(const q of pts){const v=W(q[0],q[1],q[2]);if(points.length&&points[points.length-1].distanceTo(v)<1e-4)continue;points.push(v);}
      for(let i=1;i<points.length;i++)lengths.push(lengths[i-1]+points[i-1].distanceTo(points[i]));
      walkPaths.push({name:b.name+(side>0?' left walk':' right walk'),district:b.from,bridge:Q.i,side,points,lengths,length:lengths[lengths.length-1],open:true,width:0,clearance:.12});
    }
  }

  // ---------------------------------------------------------------- crosswalks at every junction (C11.3)
  // A zebra of stripes 0.055 wide every 0.11, each stripe parallel to the traffic it crosses, drawn in the
  // street markings' own material 0.021 over the road like the dashes. At a tee it lies across the mouth
  // on the ring's walking band (from just outside the ring's kerb out 0.2, cut at the fillet curbs), from
  // one fillet tangency to the other, so the ring walkers (0.04 outside the kerb) cross the bridge's mouth
  // on it. At a fork (the rim road's two ends, the rim links' twelve) it lies across the branch, 0.2 long,
  // where the branch's carriageway has cleared the through road's sidewalk by 0.1 (and past the rim road's
  // 1.2 widening). One instanced mesh, one draw call.
  const CW_STEP=.11,CW_W=.055,CW_BAND=.2,CW_Y=.021,cwRows=[],crossings=[];
  const ringCum=new Map(),RP4={x:0,y:0,tx:0,ty:0,nx:0,ny:0};
  // A route's full centreline at arc length s (closed, as the fillets' ringS count it), with its tangent and
  // its right-hand normal (outward, the side the walkers' ring stretches use), both eased between the
  // vertices so the stripes keep an even spacing round a polygonal ring.
  function ringAt(ri,s,o){const P=D.routes[ri].points,n=P.length;
    if(!ringCum.has(ri)){const c=[0];for(let i=1;i<=n;i++)c.push(c[i-1]+Math.hypot(P[i%n][0]-P[i-1][0],P[i%n][1]-P[i-1][1]));ringCum.set(ri,c);}
    const cum=ringCum.get(ri),total=cum[n];s=((s%total)+total)%total;let lo=0,hi=n;while(lo+1<hi){const m=(lo+hi)>>1;if(cum[m]<=s)lo=m;else hi=m;}
    const a=P[lo],b=P[(lo+1)%n],t=(s-cum[lo])/((cum[lo+1]-cum[lo])||1e-9);
    const va=P[(lo-1+n)%n],vb=P[(lo+2)%n],ta=[b[0]-va[0],b[1]-va[1]],tb=[vb[0]-a[0],vb[1]-a[1]],la=Math.hypot(ta[0],ta[1])||1,lb=Math.hypot(tb[0],tb[1])||1;
    let tx=ta[0]/la+(tb[0]/lb-ta[0]/la)*t,ty=ta[1]/la+(tb[1]/lb-ta[1]/la)*t;const l=Math.hypot(tx,ty)||1;tx/=l;ty/=l;
    o.x=a[0]+(b[0]-a[0])*t;o.y=a[1]+(b[1]-a[1])*t;o.tx=tx;o.ty=ty;o.nx=ty;o.ny=-tx;return o;}
  B.forEach(Q=>Q.b.ends.forEach((e,k)=>{
    const R=ringInfo[e.route],total=(ringAt(e.route,0,RP4),ringCum.get(e.route).at(-1));
    const rel=e.fillets.map(f=>{const r=f.ringS-e.s;return R.own===null?((r%total)+total*1.5)%total-total/2:r;});
    // On a circular ring the stripes are spaced 0.11 along the band's middle line, not the centreline.
    const lo=Math.min(...rel),hi=Math.max(...rel),o0=R.roadHalf+.01,du=CW_STEP*(R.disc?R.R/(R.R+o0+CW_BAND/2):1),n=Math.floor((hi-lo)/du),first=cwRows.length;
    for(let j=0;j<n;j++){const u=(lo+hi)/2+(j-(n-1)/2)*du,q=ringAt(e.route,e.s+u,RP4);let o1=o0+CW_BAND;
      // The stripe runs outward until the band ends or the ray meets a fillet curb (radius r round its centre).
      for(const f of e.fillets){const px=q.x+q.nx*o0-f.cx,py=q.y+q.ny*o0-f.cy,bb=px*q.nx+py*q.ny,cc=px*px+py*py-(f.r+.01)**2,disc=bb*bb-cc;
        if(cc<0){o1=o0;break;}if(disc>0){const t=-bb-Math.sqrt(disc);if(t>=0)o1=Math.min(o1,o0+t);}}
      if(o1-o0<.04)continue;
      cwRows.push({x:q.x+q.nx*(o0+o1)/2,y:q.y+q.ny*(o0+o1)/2,z:e.z+CW_Y,ux:q.nx,uy:q.ny,len:o1-o0,w:CW_W});}
    crossings.push({kind:'tee',bridge:Q.i,end:k,route:e.route,z:e.z,first,count:cwRows.length-first,walk:R.roadHalf+.04,lo:e.s+lo,hi:e.s+hi});
  }));
  {const branches=[];
    D.routes.forEach((r,ri)=>{if(!r.shared)return;const pts=[[r.points[0][0],r.points[0][1],r.z]];let s=0;
      for(let i=1;i<r.points.length;i++){s+=Math.hypot(r.points[i][0]-r.points[i-1][0],r.points[i][1]-r.points[i-1][1]);if(s>r.shared[0].from+1e-4)break;pts.push([r.points[i][0],r.points[i][1],r.z]);}
      branches.push({kind:'rim',route:ri,street:-1,P:pts,half:(r.width||.88)/2,z:r.z,taper:1.2});});
    (D.streets||[]).forEach((st,k)=>branches.push({kind:'link',route:-1,street:k,P:st.points.map(q=>[q[0],q[1],st.z]),half:st.width/2,z:st.z,taper:0}));
    const P5={x:0,y:0,z:0,tx:0,ty:0,nx:0,ny:0};
    for(const br of branches){const T=track(br.P);
      for(const end of [0,1]){const E=br.P[end?br.P.length-1:0],near=[];
        // The through roads' carriageway edges near this end (every other route's own centreline).
        D.routes.forEach((r,ri)=>{if(ri===br.route)return;const R=ringInfo[ri],P=r.points,n=P.length;let m=n;
          if(R.own!==null){let s=0;m=0;for(let i=1;i<n;i++){s+=Math.hypot(P[i][0]-P[i-1][0],P[i][1]-P[i-1][1]);if(s>R.own+1e-4)break;m=i;}}
          for(let i=0;i<m;i++){const a=P[i],b=P[(i+1)%n];if(Math.min(Math.hypot(a[0]-E[0],a[1]-E[1]),Math.hypot(b[0]-E[0],b[1]-E[1]))<5)near.push([a[0],a[1],b[0],b[1],R.roadHalf]);}});
        if(!near.length)continue;
        const edgeGap=(x,y)=>{let g=Infinity;for(const q of near)g=Math.min(g,segGap(x,y,q[0],q[1],q[2],q[3])-q[4]);return g;};
        let dz=-1;for(let d=.2;d<T.L/2;d+=.02){const p=T.at(end?T.L-d:d,P5);if(edgeGap(p.x,p.y)>=br.half+.13+CW_BAND/2+.01){dz=d;break;}}
        if(dz<0)continue;dz=Math.max(dz,br.taper+CW_BAND/2);
        const p=T.at(end?T.L-dz:dz,P5),n=Math.floor((2*br.half-.06-CW_W)/CW_STEP)+1,first=cwRows.length;
        for(let j=0;j<n;j++){const m=(j-(n-1)/2)*CW_STEP;cwRows.push({x:p.x+p.nx*m,y:p.y+p.ny*m,z:br.z+CW_Y,ux:p.tx,uy:p.ty,len:CW_BAND,w:CW_W});}
        crossings.push({kind:'fork',branch:br.kind,route:br.route,street:br.street,end,z:br.z,first,count:n,d:dz,half:br.half});}}}
  const crosswalks=new THREE.InstancedMesh(new THREE.PlaneGeometry(1,1),markingMat,Math.max(1,cwRows.length));
  {const m=new THREE.Matrix4();cwRows.forEach((r,i)=>{const vx=-r.uy,vy=r.ux;
    // Columns: the stripe's width across the traffic, its length along it, up, and its centre (world x, up, -y).
    m.set(vx*r.w,r.ux*r.len,0,r.x, 0,0,1,r.z, -vy*r.w,-r.uy*r.len,0,-r.y, 0,0,0,1);crosswalks.setMatrixAt(i,m);});}
  crosswalks.count=cwRows.length;crosswalks.frustumCulled=false;crosswalks.name='crosswalks';streetGroup.add(crosswalks);

  // ---------------------------------------------------------------- packets on the beat
  // Direction per bridge and room: packets leave the end fewer bridges away from the room's district
  // (a tie goes to the nearer plateau centre). The overview (skyline) sends them out from the Compass.
  const districts=Object.keys(DATA.plateaus),hop={};
  for(const d of districts){const dist={[d]:0},queue=[d];while(queue.length){const x=queue.shift();for(const Q of B){const y=Q.b.from===x?Q.b.to:Q.b.to===x?Q.b.from:null;if(y&&dist[y]===undefined){dist[y]=dist[x]+1;queue.push(y);}}}hop[d]=dist;}
  const centreGap=(a,b)=>Math.hypot(DATA.plateaus[a].cx-DATA.plateaus[b].cx,DATA.plateaus[a].cy-DATA.plateaus[b].cy);
  const dirTable={};
  for(const d of districts)dirTable[d]=new Float32Array(16).fill(1).map((v,i)=>{if(i>=B.length)return 1;const f=B[i].b.from,t=B[i].b.to,hf=hop[d][f]??99,ht=hop[d][t]??99;
    return hf<ht?1:hf>ht?-1:centreGap(d,f)<=centreGap(d,t)?1:-1;});
  const packets={count:0,lastAt:-100,room:'',dir:deckUniforms.uDir.value,kicks:deckUniforms.uKicks.value,gains:deckUniforms.uGains.value,table:dirTable,level:0,slots:8,uniforms:deckUniforms};
  let attached=false;
  function attachLights(){
    if(attached)return;attached=true;
    beat.on('hit',h=>{
      if(h.layer!=='kick'||h.gain<=0||reduced)return;
      const K=deckUniforms.uKicks.value,Gn=deckUniforms.uGains.value;
      for(let k=7;k>0;k--){K[k]=K[k-1];Gn[k]=Gn[k-1];}
      K[0]=beat.diagnostics.lastFrameMs/1000;Gn[0]=Math.min(1,h.gain);packets.count++;packets.lastAt=K[0];
    });
  }
  function update(){
    if(!attached)return;
    const u=deckUniforms,r=rave.uniforms;
    u.uClock.value=r.uClock.value;u.uColor.value.copy(r.uColor.value);u.uTint.value=r.uEnergy.value;
    u.uPacket.value=reduced?0:r.uEnergy.value*r.uSourceIntensity.value*r.uCut.value;packets.level=u.uPacket.value;
    const slots=tier.current===3?8:tier.current===2?5:3;u.uSlots.value=slots;u.uLife.value=slots*beat.beatSeconds;packets.slots=slots;
    const room=beat.room==='skyline'?'core':beat.room;
    if(room!==packets.room&&dirTable[room]){packets.room=room;u.uDir.value.set(dirTable[room]);}
  }
  Object.assign(roadNet,{rings:ringInfo,plateaus:DATA.plateaus,deck,deckMaterial:deckMat,links,underglow,rails,railRuns,pylons,pylonRows,cables,masts,bridgeLamps:bridgeLamps.mesh,bridgeLampSpots,lampPools,
    bridgeRoutes,walkPaths,packets,attachLights,update,dims:{HALF,EDGE,WALK,DECK,TOP,CURB,FILLET},crosswalks:{mesh:crosswalks,list:crossings,stripe:{step:CW_STEP,width:CW_W,band:CW_BAND}},
    bridgeInfo:B.map(Q=>({name:Q.b.name,length:Q.L,bsA:Q.bsA,bsB:Q.bsB,s0:Q.s0,cwA:Q.cwA,cwB:Q.cwB}))});
  return true;
})();

// ------------------------------------------------------------------ traffic routing (C5.4, C7.6)
// Vehicles and the NPC light cycles drive the road graph. Every graph edge (a ring or avenue stretch
// between junctions, the rim road, a rim link, a bridge) and every turn arc through a junction fillet is a
// track in world coordinates, measured in plan like design.py. A mover travels a track in its own
// direction (edge end a to b, a turn from the ring to the bridge) or against it, at an offset to the right
// of travel (traffic keeps to the right). At a junction it takes one of the node's moves ([in edge, in end,
// out edge, out end, turn, turn direction] in the page data); a move through a fillet trims both edge ends
// to the arc's tangency points, exactly as the tour does. at() and pick() allocate nothing: distances go
// in and points come out through io, a Float64Array, so no number is boxed per frame (C13.4).
const trafficNet=roadNet&&(()=>{
  const G=roadNet.graph,E=G.edges,T=G.turns,N=G.nodes,NE=E.length,tracks=[],districtCode={};
  Object.keys(DATA.plateaus).forEach((d,i)=>{districtCode[d]=i;});
  function makeTrack(P,info){
    const pts=[];for(const p of P)if(!pts.length||Math.hypot(p[0]-pts[pts.length-1][0],p[1]-pts[pts.length-1][1])>1e-6)pts.push(p);
    const n=pts.length,x=new Float64Array(n),y=new Float64Array(n),z=new Float64Array(n),cum=new Float64Array(n),nx=new Float64Array(n),nz=new Float64Array(n);
    for(let i=0;i<n;i++){x[i]=pts[i][0];y[i]=pts[i][2];z[i]=-pts[i][1];if(i)cum[i]=cum[i-1]+Math.hypot(x[i]-x[i-1],z[i]-z[i-1]);}
    // Left normals at the vertices (along the neighbours' chord), so an offset path has no kinks.
    for(let i=0;i<n;i++){const a=Math.max(0,i-1),b=Math.min(n-1,i+1),dx=x[b]-x[a],dz=z[b]-z[a],l=Math.hypot(dx,dz)||1;nx[i]=dz/l;nz[i]=-dx/l;}
    return Object.assign({id:tracks.length,n,x,y,z,cum,nx,nz,length:cum[n-1]},info);
  }
  const rings=roadNet.rings||[];
  E.forEach(e=>{
    let half,route=-1,bridge=-1,s0=0,total=0,radius=Infinity;
    if(e.kind==='bridge'){half=roadNet.bridges[e.bridge].width/2;bridge=e.bridge;}
    else if(e.kind==='link'){half=roadNet.streets[e.street].width/2;}
    else{const r=DATA.design.routes[e.route];half=(r.width||(r.district==='episodic'?.54:.88))/2;route=e.route;s0=e.s0;
      total=routes[e.route].open?0:routes[e.route].length;if(rings[e.route]&&rings[e.route].disc)radius=rings[e.route].R;}
    tracks.push(makeTrack(roadNet.edgePoints(e),{kind:e.kind,edge:e.id,turn:-1,route,s0,total,bridge,half,lane:half>.35?.12:.1,radius,
      district:e.district||null,from:e.from||null,to:e.to||null}));
  });
  T.forEach(t=>{const end=roadNet.bridges[t.bridge].ends[t.end],f=end.fillets.find(q=>q.side===t.side);
    tracks.push(makeTrack(t.points,{kind:'turn',edge:-1,turn:t.id,route:-1,s0:0,total:0,bridge:t.bridge,half:.44,lane:.12,radius:f.r+.44,district:end.district}));});
  // Moves by arrival state (edge * 2 + the end arrived at), flattened into typed arrays.
  const lists=Array.from({length:NE*2},()=>[]);
  for(const n of N)for(const m of n.moves)lists[m[0]*2+m[1]].push(m);
  const M=lists.reduce((a,l)=>a+l.length,0),start=new Int32Array(NE*2),count=new Int32Array(NE*2);
  const mEdge=new Int32Array(M),mDir=new Int8Array(M),mTurn=new Int32Array(M),mTdir=new Int8Array(M),mTrimOut=new Float64Array(M),mTrimIn=new Float64Array(M);
  const mFar=new Int8Array(M),mBridge=new Uint8Array(M),mNext=new Int32Array(M);
  let k=0;
  lists.forEach((l,s)=>{start[s]=k;count[s]=l.length;
    for(const m of l){const e2=E[m[2]],t=m[4]>=0?T[m[4]]:null;
      mEdge[k]=m[2];mDir[k]=m[3]===0?1:-1;mTurn[k]=m[4];mTdir[k]=m[5];
      mTrimOut[k]=t?(E[m[0]].kind==='bridge'?t.trimBridge:t.trimRing):0;
      mTrimIn[k]=t?(e2.kind==='bridge'?t.trimBridge:t.trimRing):0;
      mFar[k]=districtCode[N[m[3]===0?e2.b:e2.a].district];mBridge[k]=e2.kind==='bridge'?1:0;mNext[k]=m[2]*2+(1-m[3]);k++;}});
  // toBridge[state]: the shortest drive from an arrival state to a junction with a bridge exit (0 there);
  // mCost[move]: that drive when taking the move (its edge and turn arc, then toBridge on arrival).
  const toBridge=new Float64Array(NE*2).fill(Infinity),mCost=new Float64Array(M);
  for(let pass=0,changed=true;changed&&pass<NE*2+2;pass++){changed=false;
    for(let s=0;s<NE*2;s++){let best=Infinity;
      for(let m=start[s];m<start[s]+count[s];m++){const c=mBridge[m]?0:E[mEdge[m]].length+(mTurn[m]>=0?tracks[NE+mTurn[m]].length:0)+toBridge[mNext[m]];mCost[m]=c;if(c<best)best=c;}
      if(best<toBridge[s]-1e-9){toBridge[s]=best;changed=true;}}}
  // pick(state, home, mode): mode 0 (a vehicle) gives the exits whose far junction lies in its home
  // district 70 % between them and the rest 30 %. Mode 1 (a light cycle) gives the bridge exits 75 % and
  // with no bridge exit here drives toward the nearest junction that has one, so it never strays deep into
  // the Archive's grid; mode 2 (a light cycle a while off the bridges) always takes a bridge exit.
  const rnd=mulberry(5407),bias={0:.7,1:.75,2:1};
  const inA=(m,home,mode)=>mode?mBridge[m]===1:mFar[m]===home;
  function pick(state,home,mode){
    const s=start[state],n=count[state];if(n<2)return s;
    let a=0;for(let i=0;i<n;i++)if(inA(s+i,home,mode))a++;
    const r=rnd();
    if(mode===2&&a>0){let j=Math.min(a-1,Math.floor(r*a));for(let i=0;i<n;i++)if(mBridge[s+i]===1){if(j===0)return s+i;j--;}}
    if(mode&&a===0){let best=s;for(let i=1;i<n;i++)if(mCost[s+i]<mCost[best])best=s+i;return best;}
    if(a===0||a===n)return s+Math.min(n-1,Math.floor(r*n));
    const w=bias[mode],want=r<w,size=want?a:n-a;let j=Math.min(size-1,Math.floor((want?r/w:(r-w)/(1-w))*size));
    for(let i=0;i<n;i++)if(inA(s+i,home,mode)===want){if(j===0)return s+i;j--;}
    return s;
  }
  // at(track, dir): io[0] the distance along the direction of travel from the track's start end, io[1] the
  // offset to the right of travel; writes the world point to io[2..4].
  const io=new Float64Array(8);
  function at(k,dir){
    const t=tracks[k],cum=t.cum,L=t.length;let p=dir>0?io[0]:L-io[0];if(p<0)p=0;else if(p>L)p=L;
    let lo=0,hi=t.n-1;while(lo+1<hi){const m=(lo+hi)>>1;if(cum[m]<=p)lo=m;else hi=m;}
    const seg=cum[lo+1]-cum[lo],f=seg>0?(p-cum[lo])/seg:0,off=-io[1]*dir,x=t.x,z=t.z,nx=t.nx,nz=t.nz;
    io[2]=x[lo]+(x[lo+1]-x[lo])*f+(nx[lo]+(nx[lo+1]-nx[lo])*f)*off;
    io[3]=t.y[lo]+(t.y[lo+1]-t.y[lo])*f;
    io[4]=z[lo]+(z[lo+1]-z[lo])*f+(nz[lo]+(nz[lo+1]-nz[lo])*f)*off;
  }
  return {tracks,edgeCount:NE,districtCode,start,count,mEdge,mDir,mTurn,mTdir,mTrimOut,mTrimIn,mFar,mBridge,mNext,mCost,toBridge,pick,at,io,
    state:(edge,end)=>edge*2+end};
})();
if(roadNet)roadNet.traffic=trafficNet;
