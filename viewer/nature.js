// Nature (C9, C10): the Reef lake, its shore and its life, the animals and the trees. All of it is scenery
// (B1): nothing here reads or writes cityMat or a note building's light (B2). Music-reactive light reads the
// rave uniforms, so the rave-light limiter and the Lights setting own it; reduced motion freezes every
// ambient motion (B9). Counts follow the tier: Tier 3 as specified, Tier 2 60 %, Tier 1 40 % (C13.1).
// Design data angles (trees, balconies, the beach bar) are layout angles, atan2(dx, dy); the three.js yaw
// of the same direction is PI minus that angle.
const nature=(()=>{
  const LAKE=DATA.design.lake[0],SHORE=LAKE.shore,REEF=SHORE.reef,PIER=LAKE.pier,ISLE=LAKE.island,U=rave.uniforms;
  const TREES=DATA.design.trees||[],WATER_Y=LAKE.z,BEACH_R=ISLE.r+.45;
  const COUNTS={dog:24,cat:20,pigeon:150,bat:40,capybara:6,iguana:10,heron:2,owl:4,robot:8,firefly:400,fish:60,jelly:30,boat:3,partyBoat:1};
  // The lake's people per tier (C3.7 others): Tier 2 about 60 %, Tier 1 small enough that the phone keeps venue
  // extras inside its 220 people (C13.1). crowd.js reserves their sum from each tier's extras cap.
  const LAKE_PEOPLE={riders:{3:10,2:6,1:3},strollers:{3:6,2:4,1:1},shoreFolk:{3:4,2:2,1:1}};
  const tierCount=(n,t)=>t===3||n<=1?n:Math.max(1,Math.round(n*(t===2?.6:.4)));
  const rnd=mulberry(7007),smooth01=(a,b,x)=>{const t=Math.min(1,Math.max(0,(x-a)/(b-a)));return t*t*(3-2*t);};
  const yaw3=rot=>Math.PI-rot;

  // ------------------------------------------------------------------ lake geometry (layout coordinates)
  const CA=Math.cos(LAKE.angle),SA=Math.sin(LAKE.angle),AX=LAKE.rx,BY=LAKE.ry;
  const localU=(x,y)=>(x-LAKE.cx)*CA+(y-LAKE.cy)*SA,localV=(x,y)=>-(x-LAKE.cx)*SA+(y-LAKE.cy)*CA;
  const fromLocal=(u,v,out)=>{out[0]=LAKE.cx+u*CA-v*SA;out[1]=LAKE.cy+u*SA+v*CA;return out;};
  // Signed distance to the shore, negative over water: Newton on the ellipse parameter in the first quadrant.
  function shoreGap(x,y){
    const u=Math.abs(localU(x,y)),v=Math.abs(localV(x,y)),k=AX*AX-BY*BY;let t=Math.atan2(AX*v,BY*u);
    for(let i=0;i<8;i++){const c=Math.cos(t),s=Math.sin(t),g=k*s*c-AX*u*s+BY*v*c,dg=k*(c*c-s*s)-AX*u*c-BY*v*s;
      if(Math.abs(dg)<1e-9)break;t=Math.min(Math.PI/2,Math.max(0,t-g/dg));}
    const d=Math.hypot(AX*Math.cos(t)-u,BY*Math.sin(t)-v);
    return u*u/(AX*AX)+v*v/(BY*BY)<1?-d:d;
  }
  // A point on the shore at parameter t, offset g outward (layout).
  function shorePoint(t,g,out){const nu=BY*Math.cos(t),nv=AX*Math.sin(t),k=Math.hypot(nu,nv);return fromLocal(AX*Math.cos(t)+nu/k*g,BY*Math.sin(t)+nv/k*g,out);}
  const shoreParam=(x,y)=>Math.atan2(localV(x,y)/BY,localU(x,y)/AX),shoreSpeed=t=>Math.hypot(AX*Math.sin(t),BY*Math.cos(t));
  // design_trees.py sand_height: the waterline rises to the sand top, and to the Reef sidewalk over the ramp.
  function sandHeight(x,y,gap){
    const h=SHORE.sandWater+(SHORE.sandTop-SHORE.sandWater)*smooth01(0,SHORE.sand,gap),e=Math.hypot(x-REEF.x,y-REEF.y)-REEF.outer;
    return h+(REEF.z-h)*(1-smooth01(0,SHORE.ramp,e));
  }
  const PDX=(PIER.x1-PIER.x0)/PIER.length,PDY=(PIER.y1-PIER.y0)/PIER.length;
  function pierGap(x,y){const dx=x-PIER.x0,dy=y-PIER.y0,a=Math.max(0,Math.min(PIER.length,dx*PDX+dy*PDY));return Math.hypot(dx-PDX*a,dy-PDY*a)-PIER.width/2;}
  // C8.4: the walkable height over the lake area (the pier, the island, the sand). null where nothing may stand:
  // the water, and the sand's outer bank (0.6 wide), which drops to the void, so explore.js blocks both.
  // undefined elsewhere, where the rings and the plateaus answer.
  const BANK=.6;
  function surfaceAt(x,z){
    const y=-z;
    if(pierGap(x,y)<=0)return PIER.z;
    const ri=Math.hypot(x-ISLE.x,y-ISLE.y);
    if(ri<=ISLE.r)return ISLE.z;
    if(ri<=BEACH_R)return WATER_Y+(ISLE.z-.125-WATER_Y)*(BEACH_R-ri)/(BEACH_R-ISLE.r);
    const gap=shoreGap(x,y);
    if(gap<0)return null;
    if(Math.hypot(x-REEF.x,y-REEF.y)<REEF.outer)return undefined;
    if(gap>SHORE.sand)return gap<=SHORE.sand+BANK?null:undefined;
    return sandHeight(x,y,Math.max(0,gap));
  }
  const isBlocked=(x,z)=>surfaceAt(x,z)===null,isWater=(x,z)=>isBlocked(x,z)&&shoreGap(x,-z)<SHORE.sand;

  // ------------------------------------------------------------------ builder: flat-shaded, two-sided parts
  // Every vertex carries a colour, a motion group (aPart), a light mode (aGlow), a pivot (xyz, w per part) and
  // a wind weight (aSway). Shaders flip the normal on back faces, so winding never matters.
  class NB{
    constructor(){this.p=[];this.n=[];this.c=[];this.m=[];this.g=[];this.v=[];this.s=[];this.set([1,1,1]);}
    set(color,part=0,glow=0,pivot=null,sway=0){this.col=color;this.part=part;this.glow=glow;this.pivot=pivot||[0,0,0,0];this.sw=sway;return this;}
    tri(a,b,c,sw){
      const ux=b[0]-a[0],uy=b[1]-a[1],uz=b[2]-a[2],vx=c[0]-a[0],vy=c[1]-a[1],vz=c[2]-a[2];
      let nx=uy*vz-uz*vy,ny=uz*vx-ux*vz,nz=ux*vy-uy*vx;const l=Math.hypot(nx,ny,nz)||1;nx/=l;ny/=l;nz/=l;
      const q=[a,b,c];
      for(let k=0;k<3;k++){this.p.push(q[k][0],q[k][1],q[k][2]);this.n.push(nx,ny,nz);this.c.push(...this.col);this.m.push(this.part);this.g.push(this.glow);this.v.push(...this.pivot);this.s.push(sw?sw[k]:this.sw);}
    }
    quad(a,b,c,d,sw){this.tri(a,b,c,sw&&[sw[0],sw[1],sw[2]]);this.tri(a,c,d,sw&&[sw[0],sw[2],sw[3]]);}
    box(x0,y0,z0,x1,y1,z1){
      this.quad([x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0]);this.quad([x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]);
      this.quad([x0,y0,z0],[x0,y0,z1],[x0,y1,z1],[x0,y1,z0]);this.quad([x1,y0,z0],[x1,y0,z1],[x1,y1,z1],[x1,y1,z0]);
      this.quad([x0,y1,z0],[x1,y1,z0],[x1,y1,z1],[x0,y1,z1]);this.quad([x0,y0,z0],[x1,y0,z0],[x1,y0,z1],[x0,y0,z1]);
    }
    // A square-section box between two points (a beam, a rope, a leg).
    beam(a,b,w){
      const dx=b[0]-a[0],dy=b[1]-a[1],dz=b[2]-a[2],l=Math.hypot(dx,dy,dz)||1,ax=[dx/l,dy/l,dz/l];
      let px=[ax[1],-ax[0],0];if(Math.hypot(...px)<.1)px=[0,ax[2],-ax[1]];const pl=Math.hypot(...px);px=px.map(v=>v/pl*w/2);
      const qx=[ax[1]*px[2]-ax[2]*px[1],ax[2]*px[0]-ax[0]*px[2],ax[0]*px[1]-ax[1]*px[0]];
      const at=(o,s,t)=>[o[0]+px[0]*s+qx[0]*t,o[1]+px[1]*s+qx[1]*t,o[2]+px[2]*s+qx[2]*t],r=[[1,1],[-1,1],[-1,-1],[1,-1]];
      for(let i=0;i<4;i++){const [s0,t0]=r[i],[s1,t1]=r[(i+1)%4];this.quad(at(a,s0,t0),at(a,s1,t1),at(b,s1,t1),at(b,s0,t0));}
    }
    cyl(x,z,y0,y1,r0,r1,seg,cap){
      for(let i=0;i<seg;i++){const a0=i/seg*TAU,a1=(i+1)/seg*TAU,c0=Math.cos(a0),s0=Math.sin(a0),c1=Math.cos(a1),s1=Math.sin(a1);
        this.quad([x+c0*r0,y0,z+s0*r0],[x+c1*r0,y0,z+s1*r0],[x+c1*r1,y1,z+s1*r1],[x+c0*r1,y1,z+s0*r1]);
        if(cap&&r1>0)this.tri([x,y1,z],[x+c0*r1,y1,z+s0*r1],[x+c1*r1,y1,z+s1*r1]);}
    }
    blob(x,y,z,r,sy,sway){const ico=new THREE.IcosahedronGeometry(r,0).toNonIndexed(),p=ico.attributes.position.array;
      for(let i=0;i<p.length;i+=9){const v=k=>[p[i+k]+x,p[i+k+1]*sy+y,p[i+k+2]+z];this.tri(v(0),v(3),v(6),sway&&[p[i+1],p[i+4],p[i+7]].map(s=>Math.max(0,sway+s/r*sway)));}
      ico.dispose();}
    geometry(){
      const g=new THREE.BufferGeometry(),f=(a,n)=>new THREE.Float32BufferAttribute(a,n);
      g.setAttribute('position',f(this.p,3));g.setAttribute('normal',f(this.n,3));g.setAttribute('aColor',f(this.c,3));
      g.setAttribute('aPart',f(this.m,1));g.setAttribute('aGlow',f(this.g,1));g.setAttribute('aPivot',f(this.v,4));g.setAttribute('aSway',f(this.s,1));
      return g;
    }
  }
  const C=h=>lin(hex(h));

  // ------------------------------------------------------------------ shared shading
  // aGlow: 0 lit matte, 1 eyes, 2 slow pulse, 3 bulbs on the beat, 4 steady lamp, 5 sand. Bulbs pulse with the
  // kick through the rave energy and drop with the cut, like the stage lights.
  const fireLight=new THREE.Vector4(0,0,0,1.2);
  const litUniforms=Object.assign(THREE.UniformsUtils.merge([THREE.UniformsLib.fog,{uKey:{value:KEY}}]),
    {uTime:U.uTime,uBeat:U.uBeat,uKick:U.uKick,uEnergy:U.uEnergy,uSourceIntensity:U.uSourceIntensity,uCut:U.uCut,uFire:{value:fireLight}});
  const shadeGLSL=`uniform vec3 uKey;uniform float uTime,uBeat,uKick,uEnergy,uSourceIntensity,uCut;uniform vec4 uFire;
    varying vec3 vC,vN,vW;varying float vGlow,vSeed;
    #include <fog_pars_fragment>
    float nHash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
    void main(){vec3 n=normalize(vN);if(!gl_FrontFacing)n=-n;float d=max(dot(n,uKey),0.0),up=n.y*.5+.5;vec3 c;
      vec2 fd=vW.xz-uFire.xy;float fire=uFire.z*exp(-dot(fd,fd)/(uFire.w*uFire.w))*(.4+.6*up);
      if(vGlow<.5)c=vC*(.34+.5*d+.16*up)+vec3(1.0,.45,.16)*fire*.35;
      else if(vGlow<1.5)c=vC*1.7;
      else if(vGlow<2.5)c=vC*(.75+.35*sin(uTime*3.0+vSeed*6.2831853));
      else if(vGlow<3.5){float on=step(.45,fract(floor(uBeat)*.37+vSeed));c=vC*(.3+.7*on)*(.85+.45*uKick*uEnergy*uSourceIntensity)*uCut;}
      else if(vGlow<4.5)c=vC*1.25;
      else{float grain=nHash(floor(vW.xz*60.0)),wet=1.0-smoothstep(.262,.3,vW.y);
        c=vC*(.3+.45*d+.2*up)*(.86+.2*grain)*(1.0-.45*wet)+vec3(1.0,.45,.16)*fire*.5;
        c+=vec3(.15,.75,1.0)*wet*step(.985,nHash(floor(vW.xz*90.0)+floor(uTime*1.5)))*.5;}
      gl_FragColor=vec4(c,1.0);
      #include <fog_fragment>
      #include <colorspace_fragment>
    }`;
  const shoreMat=new THREE.ShaderMaterial({fog:true,side:THREE.DoubleSide,uniforms:litUniforms,fragmentShader:shadeGLSL,
    vertexShader:`attribute vec3 aColor;attribute float aGlow,aSway;attribute vec4 aPivot;uniform float uTime;varying vec3 vC,vN,vW;varying float vGlow,vSeed;
      #include <fog_pars_vertex>
      void main(){vec3 p=position;float ph=p.x*1.7+p.z*1.3;p.x+=aSway*sin(uTime*1.3+ph)*.05;p.z+=aSway*cos(uTime*1.1+ph)*.04;
        vC=aColor;vGlow=aGlow;vSeed=aPivot.w;vN=normalize(mat3(modelMatrix)*normal);vec4 w=modelMatrix*vec4(p,1.0);vW=w.xyz;
        vec4 mvPosition=viewMatrix*w;gl_Position=projectionMatrix*mvPosition;
        #include <fog_vertex>
      }`});
  // Animals and boats: motion groups rotate about their pivot. aAnim: x gait or wing phase, y leg swing,
  // z tail wag or wing amplitude, w head angle. Tails wag on the beat (C10.1).
  const critterMat=new THREE.ShaderMaterial({fog:true,side:THREE.DoubleSide,uniforms:litUniforms,fragmentShader:shadeGLSL,
    vertexShader:`attribute vec3 aColor;attribute float aPart,aGlow;attribute vec4 aPivot,aAnim;uniform float uBeat;varying vec3 vC,vN,vW;varying float vGlow,vSeed;
      #include <fog_pars_vertex>
      mat3 rx(float a){float c=cos(a),s=sin(a);return mat3(1.0,0.0,0.0,0.0,c,s,0.0,-s,c);}
      mat3 ry(float a){float c=cos(a),s=sin(a);return mat3(c,0.0,-s,0.0,1.0,0.0,s,0.0,c);}
      mat3 rz(float a){float c=cos(a),s=sin(a);return mat3(c,s,0.0,-s,c,0.0,0.0,0.0,1.0);}
      void main(){vec3 p=position,n=normal;
        if(aPart>1.5){mat3 R;
          if(aPart<2.5)R=ry(aAnim.z*cos(3.14159265*uBeat*aPivot.w));
          else if(aPart<3.5)R=rx(aAnim.y*sin(aAnim.x));
          else if(aPart<4.5)R=rx(-aAnim.y*sin(aAnim.x));
          else if(aPart<5.5)R=rz(aAnim.z*sin(aAnim.x));
          else if(aPart<6.5)R=rz(-aAnim.z*sin(aAnim.x));
          else R=aPivot.w>.5?rx(aAnim.w):ry(aAnim.w);
          p=R*(p-aPivot.xyz)+aPivot.xyz;n=R*n;}
        vC=aGlow<.5?aColor*instanceColor:aColor;vGlow=aGlow;vSeed=aPivot.w;
        vN=normalize(mat3(modelMatrix)*mat3(instanceMatrix)*n);vec4 w=modelMatrix*instanceMatrix*vec4(p,1.0);vW=w.xyz;
        vec4 mvPosition=viewMatrix*w;gl_Position=projectionMatrix*mvPosition;
        #include <fog_vertex>
      }`});
  // Plants: trunks stretch to the height (aSize.x) and thickness (aSize.z), crowns scale (aSize.y) and sit on
  // top; aPart 2 is placed by the instance matrix alone (balcony plants). Wind moves the crowns.
  const plantMat=new THREE.ShaderMaterial({fog:true,side:THREE.DoubleSide,uniforms:litUniforms,fragmentShader:shadeGLSL,
    vertexShader:`attribute vec3 aColor,aSize;attribute float aPart,aGlow,aSway;attribute vec4 aPivot;uniform float uTime;varying vec3 vC,vN,vW;varying float vGlow,vSeed;
      #include <fog_pars_vertex>
      void main(){vec3 p=position;float k=1.0;
        if(aPart<.5)p=vec3(p.x*aSize.z,p.y*aSize.x,p.z*aSize.z);else if(aPart<1.5){p=p*aSize.y+vec3(0.0,aSize.x,0.0);k=aSize.y;}
        float ph=instanceMatrix[3].x*.7+instanceMatrix[3].z*.4;p.x+=aSway*sin(uTime*1.1+ph)*.045*k;p.z+=aSway*cos(uTime*.83+ph)*.035*k;
        vC=aGlow<.5&&aPart>.5&&aPart<1.5?aColor*instanceColor:aColor;vGlow=aGlow;vSeed=aPivot.w;
        vN=normalize(mat3(modelMatrix)*mat3(instanceMatrix)*normal);vec4 w=modelMatrix*instanceMatrix*vec4(p,1.0);vW=w.xyz;
        vec4 mvPosition=viewMatrix*w;gl_Position=projectionMatrix*mvPosition;
        #include <fog_vertex>
      }`});
  const group=new THREE.Group();group.name='nature';scene.add(group);
  function instancedOf(geometry,material,count,extra){
    const mesh=new THREE.InstancedMesh(geometry,material,Math.max(1,count));mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);mesh.frustumCulled=false;
    const white=new THREE.Color(1,1,1);for(let i=0;i<mesh.count;i++){mesh.setColorAt(i,white);mesh.setMatrixAt(i,new THREE.Matrix4().makeScale(0,0,0));}
    for(const [name,size] of extra||[])geometry.setAttribute(name,new THREE.InstancedBufferAttribute(new Float32Array(mesh.count*size),size).setUsage(THREE.DynamicDrawUsage));
    group.add(mesh);return mesh;
  }
  // One matrix writer: T * Ry(yaw) * Rx(pitch) * Rz(roll) * S. Writes the array in place, no allocation.
  function put(arr,i,x,y,z,yaw,sx,sy,sz,pitch,roll){
    const cy=Math.cos(yaw),syw=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch),cr=Math.cos(roll),sr=Math.sin(roll),o=i*16;
    arr[o]=(cy*cr+syw*sp*sr)*sx;arr[o+1]=cp*sr*sx;arr[o+2]=(-syw*cr+cy*sp*sr)*sx;arr[o+3]=0;
    arr[o+4]=(-cy*sr+syw*sp*cr)*sy;arr[o+5]=cp*cr*sy;arr[o+6]=(syw*sr+cy*sp*cr)*sy;arr[o+7]=0;
    arr[o+8]=syw*cp*sz;arr[o+9]=-sp*sz;arr[o+10]=cy*cp*sz;arr[o+11]=0;
    arr[o+12]=x;arr[o+13]=y;arr[o+14]=z;arr[o+15]=1;
  }
  const hideAt=(arr,i)=>{const o=i*16;for(let k=0;k<16;k++)arr[o+k]=0;};
  const P2=[0,0],P3=[0,0],V3=new THREE.Vector3(),V4=new THREE.Vector3();

  // ------------------------------------------------------------------ trees and plants (C10.2), placed by design.py
  const palms=TREES.filter(t=>t.kind==='palm'),broad=TREES.filter(t=>t.kind==='tropical'),balconies=TREES.filter(t=>t.kind==='balcony');
  const isLakeTree=t=>t.at==='lake'||t.at==='hammock';
  function sandFree(x,y,margin,treeMargin=margin){const gap=shoreGap(x,y);if(gap<.18||gap>SHORE.sand-.2)return false;if(Math.hypot(x-REEF.x,y-REEF.y)<REEF.outer+.35)return false;
    if(Math.hypot(x-SHORE.bar.x,y-SHORE.bar.y)<.9||(SHORE.bonfire&&Math.hypot(x-SHORE.bonfire.x,y-SHORE.bonfire.y)<.55)||pierGap(x,y)<margin)return false;
    for(const t of TREES)if(t.kind!=='balcony'&&isLakeTree(t)&&Math.hypot(x-t.x,y-t.y)<(t.kind==='palm'?.08:.1)+treeMargin)return false;return true;}

  // ------------------------------------------------------------------ the shore (C9.4): one static mesh
  const shore=new NB();
  {
    const SAND=C('#8a7556'),WET=C('#5d4f3d'),N=192,G=[-.32,0,.2,.5,.9,SHORE.sand],sandAt=(t,g,out)=>{
      shorePoint(t,g,out);const dx=out[0]-REEF.x,dy=out[1]-REEF.y,r=Math.hypot(dx,dy);
      if(r<REEF.outer){out[0]=REEF.x+dx/r*REEF.outer;out[1]=REEF.y+dy/r*REEF.outer;}
      return out;};
    const ring=[];
    for(let i=0;i<=N;i++){const t=i/N*TAU,row=[];
      for(const g of G){sandAt(t,g,P2);const y=g<0?SHORE.sandWater+g/.32*.1:sandHeight(P2[0],P2[1],Math.max(0,shoreGap(P2[0],P2[1])));row.push(W(P2[0],P2[1],y));}
      sandAt(t,SHORE.sand+.4,P2);row.push(W(P2[0],P2[1],-.02));ring.push(row);}
    for(let i=0;i<N;i++)for(let k=0;k<G.length;k++){const a=ring[i][k],b=ring[i+1][k],c=ring[i+1][k+1],d=ring[i][k+1];
      shore.set(k===0?WET:k===G.length-1?C('#2e2820'):SAND,0,k<G.length-1?5:0);
      shore.quad([a.x,a.y,a.z],[b.x,b.y,b.z],[c.x,c.y,c.z],[d.x,d.y,d.z]);}
    // The island under the Reef Island Stage: a beach ring rising to the stage deck.
    const iz=ISLE.z-.125,ic=W(ISLE.x,ISLE.y,0);
    shore.set(SAND,0,5);shore.cyl(ic.x,ic.z,WATER_Y,iz,BEACH_R,ISLE.r,40,true);
    shore.set(WET,0,5);shore.cyl(ic.x,ic.z,.08,WATER_Y,BEACH_R+.3,BEACH_R,40,false);
    // The pier: 0.5 wide and 5 long, posts into the water, rails and lamps (C9.4).
    const a=W(PIER.x0,PIER.y0,PIER.z),b=W(PIER.x1,PIER.y1,PIER.z),dir=b.clone().sub(a).normalize(),side=new THREE.Vector3(-dir.z,0,dir.x),hw=PIER.width/2;
    const pt=(s,l,y)=>[a.x+dir.x*s+side.x*l,y,a.z+dir.z*s+side.z*l];
    for(let s=0;s<PIER.length-1e-6;s+=.25){const e=Math.min(PIER.length,s+.25);shore.set(Math.round(s/.25)%2?C('#4a3a2c'):C('#55432f'));
      shore.quad(pt(s,-hw,PIER.z),pt(e,-hw,PIER.z),pt(e,hw,PIER.z),pt(s,hw,PIER.z));shore.quad(pt(s,-hw,PIER.z-.05),pt(e,-hw,PIER.z-.05),pt(e,hw,PIER.z-.05),pt(s,hw,PIER.z-.05));}
    for(const l of [-hw,hw])shore.quad(pt(0,l,PIER.z-.05),pt(PIER.length,l,PIER.z-.05),pt(PIER.length,l,PIER.z),pt(0,l,PIER.z));
    shore.set(C('#2f261d'));
    for(let s=.3;s<PIER.length;s+=.62)for(const l of [-hw+.03,hw-.03])shore.beam(pt(s,l,.05),pt(s,l,PIER.z+.17),.035);
    for(const l of [-hw+.03,hw-.03])shore.beam(pt(.3,l,PIER.z+.16),pt(PIER.length-.1,l,PIER.z+.16),.018);
    for(let s=.6,k=0;s<PIER.length;s+=1.25,k++){const l=(k%2?1:-1)*(hw-.03),q=pt(s,l,PIER.z);shore.set(C('#20242a'));shore.beam(q,pt(s,l,PIER.z+.32),.02);
      shore.set(C('#ffd49a'),0,4);shore.box(q[0]-.025,PIER.z+.32,q[2]-.025,q[0]+.025,PIER.z+.37,q[2]+.025);}
    // The beach bar: a palapa on a deck, a lit counter facing the water, bottles and bulbs on the beat.
    const bar=SHORE.bar,bc=W(bar.x,bar.y,bar.z),by=yaw3(bar.rot),cb=Math.cos(by),sb=Math.sin(by);
    const at=(x,y,z)=>[bc.x+x*cb+z*sb,bc.y+y,bc.z-x*sb+z*cb];
    const bbox=(x0,y0,z0,x1,y1,z1)=>{const c=[[x0,z0],[x1,z0],[x1,z1],[x0,z1]].map(([x,z])=>at(x,0,z));
      for(let i=0;i<4;i++){const p=c[i],q=c[(i+1)%4];shore.quad([p[0],bc.y+y0,p[2]],[q[0],bc.y+y0,q[2]],[q[0],bc.y+y1,q[2]],[p[0],bc.y+y1,p[2]]);}
      shore.quad(...c.map(p=>[p[0],bc.y+y1,p[2]]));shore.quad(...c.map(p=>[p[0],bc.y+y0,p[2]]));};
    shore.set(C('#4f3b28'));bbox(-.5,-.2,-.42,.5,.04,.42);
    shore.set(C('#3a2c1e'));for(const [x,z] of [[-.46,-.38],[.46,-.38],[-.46,.38],[.46,.38]])shore.beam(at(x,.04,z),at(x,.58,z),.04);
    const apex=at(0,.9,0),eave=[[-.64,-.55],[.64,-.55],[.64,.55],[-.64,.55]].map(([x,z])=>at(x,.5,z));
    shore.set(C('#8c7442'));for(let i=0;i<4;i++)shore.tri(eave[i],eave[(i+1)%4],apex);
    shore.set(C('#6e5530'));for(let i=0;i<4;i++){const p=eave[i],q=eave[(i+1)%4];shore.quad(p,q,[q[0],q[1]-.06,q[2]],[p[0],p[1]-.06,p[2]]);}
    shore.set(C('#5a4330'));bbox(-.4,.04,.2,.4,.26,.33);shore.set(C('#ffb45e'),0,4);bbox(-.38,.12,.331,.38,.14,.336);
    shore.set(C('#2a2f36'));bbox(-.36,.3,-.36,.36,.33,-.3);
    for(let k=0;k<6;k++){shore.set(C(['#3fae5a','#e0b040','#b04030','#6fc2d8','#e8e2d0','#3fae5a'][k]),0,4);bbox(-.3+k*.11,.33,-.345,-.27+k*.11,.4,-.325);}
    for(let i=0;i<4;i++){const p=eave[i],q=eave[(i+1)%4];for(let k=0;k<9;k++){const f=(k+.5)/9,x=p[0]+(q[0]-p[0])*f,z=p[2]+(q[2]-p[2])*f,y=p[1]-.08-Math.sin(f*Math.PI)*.05;
      shore.set(C(['#ffd060','#ff5fa2','#5ee6ff','#8cff6a'][(i+k)%4]),0,3,[0,0,0,((i*9+k)*.618)%1]);shore.box(x-.013,y-.013,z-.013,x+.013,y+.013,z+.013);}}
    // Hammocks between their palms (design_trees.py places the palms): striped cloth that sways.
    for(const [ax,ay,bx,by2] of SHORE.hammocks||[]){
      const p0=W(ax,ay,sandHeight(ax,ay,Math.max(0,shoreGap(ax,ay)))+.34),p1=W(bx,by2,sandHeight(bx,by2,Math.max(0,shoreGap(bx,by2)))+.34);
      const d=p1.clone().sub(p0),sx=-d.z/d.length()*.08,sz=d.x/d.length()*.08,seg=8,sag=f=>.16*Math.sin(f*Math.PI);
      for(let k=0;k<seg;k++){const f0=k/seg,f1=(k+1)/seg,w0=Math.sin(f0*Math.PI),w1=Math.sin(f1*Math.PI);
        const q0=[p0.x+d.x*f0,p0.y+d.y*f0-sag(f0),p0.z+d.z*f0],q1=[p0.x+d.x*f1,p0.y+d.y*f1-sag(f1),p0.z+d.z*f1];
        shore.set(C(k%2?'#d9482b':'#f0c24a'));
        shore.quad([q0[0]-sx*w0,q0[1],q0[2]-sz*w0],[q1[0]-sx*w1,q1[1],q1[2]-sz*w1],[q1[0]+sx*w1,q1[1],q1[2]+sz*w1],[q0[0]+sx*w0,q0[1],q0[2]+sz*w0],[w0*.6,w1*.6,w1*.6,w0*.6]);}}
    // The bonfire: a ring of stones, crossed logs and log seats; the flames are points (below).
    if(SHORE.bonfire){const f=W(SHORE.bonfire.x,SHORE.bonfire.y,SHORE.bonfire.z);fireLight.set(f.x,f.z,1,1.3);
      shore.set(C('#3b3a38'));for(let k=0;k<9;k++){const a2=k/9*TAU;shore.box(f.x+Math.cos(a2)*.13-.025,f.y-.01,f.z+Math.sin(a2)*.13-.025,f.x+Math.cos(a2)*.13+.025,f.y+.035,f.z+Math.sin(a2)*.13+.025);}
      shore.set(C('#3a2616'));for(let k=0;k<3;k++){const a2=k/3*Math.PI;shore.beam([f.x-Math.cos(a2)*.1,f.y+.015,f.z-Math.sin(a2)*.1],[f.x+Math.cos(a2)*.1,f.y+.05,f.z+Math.sin(a2)*.1],.025);}
      for(let k=0;k<3;k++){const a2=k/3*TAU+.4,x=f.x+Math.cos(a2)*.36,z=f.z+Math.sin(a2)*.36,s=surfaceAt(x,z)??f.y,tx=-Math.sin(a2)*.07,tz=Math.cos(a2)*.07;
        shore.set(C('#4a3220'));shore.beam([x-tx,s+.03,z-tz],[x+tx,s+.03,z+tz],.055);}
      shore.set(C('#ff7a2a'),0,4);shore.box(f.x-.05,f.y+.01,f.z-.05,f.x+.05,f.y+.03,f.z+.05);}
    // Reeds in the shallows, away from the pier, the bar front and the Reef ring.
    const reedRnd=mulberry(515);
    for(let cl=0;cl<26;cl++){
      const t=reedRnd()*TAU;shorePoint(t,-.08-reedRnd()*.12,P3);
      if(pierGap(P3[0],P3[1])<1.0||Math.hypot(P3[0]-bar.x,P3[1]-bar.y)<1.4||Math.hypot(P3[0]-REEF.x,P3[1]-REEF.y)<REEF.outer+.4)continue;
      for(let k=0;k<13;k++){const x=P3[0]+(reedRnd()-.5)*.4,y=P3[1]+(reedRnd()-.5)*.4,h=.16+reedRnd()*.2,a2=reedRnd()*TAU,l=reedRnd()*.05,base=W(x,y,WATER_Y-.02);
        const tip=[base.x+Math.cos(a2+1)*l,base.y+h,base.z+Math.sin(a2+1)*l];
        shore.set(C(k%4?'#3f5a2a':'#6b7a3a'));shore.tri([base.x-Math.cos(a2)*.012,base.y,base.z-Math.sin(a2)*.012],[base.x+Math.cos(a2)*.012,base.y,base.z+Math.sin(a2)*.012],tip,[0,0,1]);
        if(k%5===0){shore.set(C('#4a3320'),0,0,null,1);shore.beam(tip,[tip[0],tip[1]+.05,tip[2]],.018);}}
    }
  }
  const shoreMesh=new THREE.Mesh(shore.geometry(),shoreMat);shoreMesh.frustumCulled=false;group.add(shoreMesh);

  // ------------------------------------------------------------------ the water (C9.2)
  // The reflection is the sky itself: the reflected view ray goes through rave-light's raveSky(), so the
  // lake flashes with the sky, through the same limiter. Kick rings leave the island stage; boats and people
  // on the wet sand leave a bioluminescent wake; coral glows through the shallows. No planar reflector.
  const kicks=new Float32Array(8).fill(-100);let kickHead=0;
  const boatPaths=Array.from({length:4},()=>new THREE.Vector4()),boatState=Array.from({length:4},()=>new THREE.Vector4()),walkGlow=Array.from({length:12},()=>new THREE.Vector4());
  const cityDir=new THREE.Vector2(-LAKE.cx,LAKE.cy).normalize();
  const waterUniforms=Object.assign({},U,THREE.UniformsUtils.clone(THREE.UniformsLib.fog),{
    uKicks:{value:kicks},uLakeXf:{value:new THREE.Vector4(LAKE.cx,LAKE.cy,CA,SA)},uAxes:{value:new THREE.Vector2(AX,BY)},
    uIsle:{value:new THREE.Vector3(ISLE.x,ISLE.y,BEACH_R)},uPath:{value:boatPaths},uBoat:{value:boatState},uWalk:{value:walkGlow},
    uCity:{value:new THREE.Vector3(cityDir.x,cityDir.y,.3)},uStageLight:{value:W(ISLE.x,ISLE.y,ISLE.z+1.3)}});
  const waterMat=new THREE.ShaderMaterial({fog:true,depthWrite:false,uniforms:waterUniforms,
    vertexShader:`varying vec3 vWorld;
      #include <fog_pars_vertex>
      void main(){vec4 w=modelMatrix*vec4(position,1.0);vWorld=w.xyz;vec4 mvPosition=viewMatrix*w;gl_Position=projectionMatrix*mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader:`varying vec3 vWorld;
      ${rave.skyGLSL}
      uniform float uClock,uKicks[8];uniform vec4 uLakeXf,uPath[4],uBoat[4],uWalk[12];uniform vec2 uAxes;uniform vec3 uIsle,uCity,uStageLight;
      #include <fog_pars_fragment>
      float wHash(vec2 p){return fract(sin(dot(p,vec2(41.3,289.1)))*43758.5453);}
      float wNoise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(wHash(i),wHash(i+vec2(1,0)),f.x),mix(wHash(i+vec2(0,1)),wHash(i+1.0),f.x),f.y);}
      void main(){
        vec2 L=vec2(vWorld.x,-vWorld.z),d=L-uLakeXf.xy,uv=vec2(d.x*uLakeXf.z+d.y*uLakeXf.w,-d.x*uLakeXf.w+d.y*uLakeXf.z);
        vec2 q=uv/uAxes,gr=2.0*uv/(uAxes*uAxes);float shore=max(0.0,-(dot(q,q)-1.0)/max(length(gr),1e-3));
        vec2 toIsle=L-uIsle.xy;float ri=length(toIsle),depth=min(shore,max(ri-uIsle.z,0.0));
        float t=uTime;vec2 p=vWorld.xz,slope=vec2(.8,.6)*cos(dot(p,vec2(.8,.6))*9.0+t*1.9)*.035+vec2(-.3,.95)*cos(dot(p,vec2(-.3,.95))*5.3+t*1.3)*.045+vec2(.97,-.25)*cos(dot(p,vec2(.97,-.25))*14.0+t*2.6)*.02;
        float rings=0.0;vec2 radial=vec2(toIsle.x,-toIsle.y)/max(ri,1e-3);
        for(int i=0;i<8;i++){float age=uClock-uKicks[i];if(age<0.0||age>2.0)continue;float x=(ri-uIsle.z-.15-age*2.4)*7.0,fade=1.0-age*.5,e=exp(-x*x);rings+=e*fade;slope-=radial*x*e*.05*fade;}
        vec3 n=normalize(vec3(-slope.x,1.0,-slope.y)),V=normalize(cameraPosition-vWorld),R=reflect(-V,n);R.y=max(R.y,.015);R=normalize(R);
        float F=.02+.98*pow(1.0-max(dot(n,V),0.0),5.0);
        // The sky, and the city's glow on the reflected horizon toward the city.
        vec3 sky=raveSky(R)*1.6;
        float az=max(0.0,dot(normalize(R.xz),uCity.xy));sky+=mix(uColor,vec3(1.0,.62,.35),.4)*pow(az,3.0)*exp(-R.y*7.0)*uCity.z*uEnergy*uCut;
        // Glints of the island stage's light on the wind waves, in the room colour.
        vec3 toL=uStageLight-vWorld;float dl=length(toL);vec3 H=normalize(toL/dl+V);
        float glint=pow(max(dot(n,H),0.0),70.0)*(.5+.5*uEnergy)*(1.0+.4*uKick*uEnergy*uSourceIntensity)/(1.0+dl*dl*.03);
        float shallow=exp(-depth*1.6),cell=wNoise(L*3.1)*.6+wNoise(L*7.1+7.0)*.4,coral=smoothstep(.55,.82,cell);
        vec3 body=vec3(.003,.016,.023)+vec3(.01,.045,.045)*shallow;
        body+=mix(vec3(.08,.7,.55),vec3(.95,.3,.5),wNoise(L*.7))*coral*shallow*.3*(.75+.25*sin(t*.6+cell*6.0));
        float wake=0.0;
        for(int k=0;k<4;k++){vec4 P=uPath[k],B=uBoat[k];if(B.z<=0.0)continue;vec2 e=(uv-P.xy)/P.zw;float dist=abs(dot(e,e)-1.0)/max(length(2.0*e/P.zw),1e-3);
          float behind=mod((B.x-atan(e.y,e.x))*B.y,6.2831853),along=behind*(P.z+P.w)*.5,width=.05+.06*along;wake+=B.z*exp(-dist*dist/(width*width))*exp(-along*.6)*step(along,6.0);}
        float walk=0.0;for(int k=0;k<12;k++){vec4 w=uWalk[k];if(w.z<=0.0)continue;vec2 dd=L-w.xy;walk+=w.z*exp(-dot(dd,dd)*4.0);}walk*=exp(-shore*2.5);
        float spark=.3+1.4*smoothstep(.5,.95,wNoise(L*34.0+vec2(t*.7,-t*.4)));
        vec3 c=mix(body,sky,F)+mix(uColor,vec3(.4,1.0,.9),.35)*glint*.9*uCut+vec3(.15,.8,1.0)*(wake*.3+walk*.34)*spark+mix(uColor,vec3(.2,.9,1.0),.5)*rings*.11*uEnergy*uSourceIntensity*uCut;
        gl_FragColor=vec4(c,1.0);
        #include <fog_fragment>
        #include <colorspace_fragment>
      }`});
  // The lake draws after the opaque world without writing depth, so what glows under it (fish, jellies)
  // still shows through, while the shore, pier, island and boats in front of it hide it as usual.
  const water=(()=>{
    const pos=[LAKE.cx,WATER_Y,-LAKE.cy],idx=[],R=24,S=128;
    for(let r=1;r<=R;r++)for(let s=0;s<S;s++){const f=Math.pow(r/R,.8),t=s/S*TAU;fromLocal(AX*f*Math.cos(t),BY*f*Math.sin(t),P2);pos.push(P2[0],WATER_Y,-P2[1]);}
    // Counterclockwise seen from above (layout angles run counterclockwise on screen too).
    for(let s=0;s<S;s++)idx.push(0,1+s,1+(s+1)%S);
    for(let r=1;r<R;r++)for(let s=0;s<S;s++){const a=1+(r-1)*S+s,b=1+(r-1)*S+(s+1)%S,c=1+r*S+(s+1)%S,d=1+r*S+s;idx.push(a,c,b,a,d,c);}
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));g.setIndex(idx);
    const mesh=new THREE.Mesh(g,waterMat);mesh.renderOrder=2;mesh.frustumCulled=false;group.add(mesh);return mesh;})();
  beat.on('hit',hit=>{if(reduced||hit.layer!=='kick'||hit.gain<=0)return;kicks[kickHead]=beat.diagnostics.lastFrameMs/1000;kickHead=(kickHead+1)%8;});

  // ------------------------------------------------------------------ tree geometry and instances
  function palmGeometry(){
    const g=new NB(),seg=7;
    for(let k=0;k<seg;k++){const y0=k/seg,y1=(k+1)/seg;g.set(C(k%2?'#8f8a7e':'#a39d8e'));g.cyl(0,0,y0,y1,.052-.012*y0,.052-.012*y1,6,false);}
    g.set(C('#6f7a4a'),1);g.cyl(0,0,-.16,.02,.05,.07,6,true);
    const FR=11;
    for(let f=0;f<FR;f++){const a=f/FR*TAU+(f%2)*.2,up=f%3===0?.35:0,ca=Math.cos(a),sa=Math.sin(a),pts=[[0,.02],[.2,.12+up*.3],[.42,.04+up*.25],[.6,-.14+up*.1]];
      g.set(C(f%2?'#2c5a30':'#356a36'),1);
      for(let k=0;k<3;k++){const p=pts[k],q=pts[k+1],w0=.07*(1-k/3)+.02,w1=.07*(1-(k+1)/3)+.01,P=(v,w)=>[v[0]*ca-w*sa,v[1],v[0]*sa+w*ca];
        g.quad(P(p,-w0),P(q,-w1),P(q,w1),P(p,w0),[k/3,(k+1)/3,(k+1)/3,k/3]);}}
    return g.geometry();
  }
  function broadGeometry(){
    const g=new NB();
    g.set(C('#4a3a2a'));g.cyl(0,0,0,1,.1,.07,7,false);g.beam([0,.7,0],[.25,1.02,.05],.05);g.beam([0,.75,0],[-.2,1.0,-.08],.045);
    for(const [x,y,z,r] of [[0,.1,0,.62],[.38,-.05,.12,.42],[-.34,0,-.1,.44],[.05,.28,-.3,.38],[-.1,-.08,.36,.4],[.2,.35,.2,.32]]){g.set(C(y>.2?'#2f5c2c':'#244a24'),1);g.blob(x,y,z,r,.8,.6);}
    for(let k=0;k<7;k++){const a=k*2.4,r=.35+.25*(k%3)/2;g.set(C(['#ff7a3a','#ffd23a','#ff4f7a'][k%3]),1,4);g.box(Math.cos(a)*r-.025,.25+k%2*.12,Math.sin(a)*r-.025,Math.cos(a)*r+.025,.3+k%2*.12,Math.sin(a)*r+.025);}
    return g.geometry();
  }
  function balconyGeometry(){
    const g=new NB();g.set(C('#8a4a32'),2);g.box(-.5,0,0,.5,.05,.07);g.set(C('#c9c2b0'),2);g.box(-.5,-.012,0,.5,0,.1);
    for(let k=0;k<6;k++){const x=-.42+k*.168;g.set(C(k%2?'#2f6a34':'#3d7a3a'),2,0,null,.15);g.blob(x,.08,.04,.06,1,.15);
      g.set(C(['#ff5a7a','#ffd24a','#ff8a3a','#e05aff'][k%4]),2,4);g.box(x-.015,.11,.075,x+.015,.13,.09);}
    return g.geometry();
  }
  const palmMesh=instancedOf(palmGeometry(),plantMat,palms.length,[['aSize',3]]);
  const broadMesh=instancedOf(broadGeometry(),plantMat,broad.length,[['aSize',3]]);
  const balconyMesh=instancedOf(balconyGeometry(),plantMat,balconies.length,[['aSize',3]]);
  const tint=new THREE.Color();
  palms.forEach((t,i)=>{const p=W(t.x,t.y,t.z),lake=isLakeTree(t),yaw=yaw3(t.rot),lean=t.lean||0;
    put(palmMesh.instanceMatrix.array,i,p.x,p.y,p.z,yaw,1,1,1,lean,0);
    palmMesh.geometry.attributes.aSize.setXYZ(i,t.h,lake?.72:1.05,lake?1.25:1);palmMesh.setColorAt(i,tint.setHSL(.28+rnd()*.06,.35,.5+rnd()*.25));
    t.world=p;t.top=new THREE.Vector3(p.x+Math.sin(yaw)*Math.sin(lean)*t.h,p.y+Math.cos(lean)*t.h,p.z+Math.cos(yaw)*Math.sin(lean)*t.h);});
  broad.forEach((t,i)=>{const p=W(t.x,t.y,t.z);put(broadMesh.instanceMatrix.array,i,p.x,p.y,p.z,yaw3(t.rot),1,1,1,0,0);
    broadMesh.geometry.attributes.aSize.setXYZ(i,t.h*.6,t.h*.42,t.h*.35);broadMesh.setColorAt(i,tint.setHSL(.26+rnd()*.08,.4,.5+rnd()*.3));t.world=p;});
  balconies.forEach((t,i)=>{t.node=byId.get(t.host);balconyMesh.geometry.attributes.aSize.setXYZ(i,1,1,1);});
  for(const m of [palmMesh,broadMesh,balconyMesh]){m.instanceMatrix.needsUpdate=true;m.instanceColor.needsUpdate=true;m.geometry.attributes.aSize.needsUpdate=true;}

  // ------------------------------------------------------------------ animal and boat geometry (C10.1, C9.3)
  const COAT=C('#ffffff'),DARK=C('#1a1614');
  function dogGeometry(){const g=new NB();
    g.set(COAT);g.box(-.035,.065,-.075,.035,.115,.065);g.box(-.03,.1,.055,.03,.15,.105);g.set(C('#c8c0b4'));g.box(-.018,.1,.1,.018,.125,.14);
    g.set(DARK);g.box(-.009,.112,.138,.009,.124,.143);g.set(COAT);g.tri([-.03,.15,.07],[-.012,.15,.07],[-.028,.18,.08]);g.tri([.03,.15,.07],[.012,.15,.07],[.028,.18,.08]);
    for(const [x,z,part] of [[-.022,.045,3],[.022,-.055,3],[.022,.045,4],[-.022,-.055,4]]){g.set(COAT,part,0,[x,.075,z,0]);g.box(x-.01,0,z-.01,x+.01,.075,z+.01);}
    g.set(COAT,2,0,[0,.105,-.07,1]);g.beam([0,.105,-.07],[0,.15,-.125],.016);return g.geometry();}
  function catGeometry(){const g=new NB();
    g.set(COAT);g.box(-.024,0,-.035,.024,.06,.02);g.box(-.02,.045,-.005,.02,.075,.03);
    g.set(COAT,7,0,[0,.075,.02,0]);g.box(-.021,.07,.0,.021,.105,.035);g.tri([-.02,.105,.01],[-.006,.105,.01],[-.016,.128,.015]);g.tri([.02,.105,.01],[.006,.105,.01],[.016,.128,.015]);
    g.set(C('#b8ff5a'),7,1,[0,.075,.02,0]);g.box(-.013,.09,.035,-.005,.096,.037);g.box(.005,.09,.035,.013,.096,.037);
    g.set(COAT,2,0,[0,.01,-.035,.25]);g.beam([0,.01,-.035],[.03,.0,-.09],.01);g.beam([.03,.0,-.09],[.05,.035,-.11],.01);return g.geometry();}
  function pigeonGeometry(){const g=new NB();
    g.set(C('#8a8f99'));g.box(-.014,.012,-.03,.014,.036,.02);g.set(C('#4f7a74'),7,0,[0,.034,.018,1]);g.box(-.01,.032,.014,.01,.052,.034);g.set(C('#d49a5a'),7,0,[0,.034,.018,1]);g.box(-.003,.04,.034,.003,.045,.042);
    g.set(C('#707782'),5,0,[-.012,.032,0,0]);g.quad([-.012,.032,.012],[-.06,.034,.004],[-.058,.034,-.018],[-.012,.032,-.022]);
    g.set(C('#707782'),6,0,[.012,.032,0,0]);g.quad([.012,.032,.012],[.06,.034,.004],[.058,.034,-.018],[.012,.032,-.022]);
    g.set(C('#5a5f68'));g.quad([-.01,.03,-.03],[.01,.03,-.03],[.014,.03,-.055],[-.014,.03,-.055]);g.set(C('#c86a5a'));g.box(-.006,0,-.004,.006,.012,.004);return g.geometry();}
  function batGeometry(){const g=new NB(),b=C('#2a2226');
    g.set(b);g.box(-.008,-.008,-.016,.008,.008,.016);g.box(-.006,-.004,.014,.006,.008,.026);
    g.set(b,5,0,[-.008,0,0,0]);g.tri([-.008,0,.01],[-.07,.006,.0],[-.008,0,-.012]);g.tri([-.07,.006,0],[-.05,0,-.022],[-.008,0,-.012]);
    g.set(b,6,0,[.008,0,0,0]);g.tri([.008,0,.01],[.07,.006,.0],[.008,0,-.012]);g.tri([.07,.006,0],[.05,0,-.022],[.008,0,-.012]);return g.geometry();}
  function capybaraGeometry(){const g=new NB();
    g.set(COAT);g.box(-.055,.05,-.11,.055,.14,.08);g.set(COAT,7,0,[0,.12,.075,1]);g.box(-.04,.07,.07,.04,.14,.16);g.box(-.04,.14,.08,-.025,.155,.095);g.box(.025,.14,.08,.04,.155,.095);
    g.set(DARK,7,0,[0,.12,.075,1]);g.box(-.03,.075,.155,.03,.1,.165);
    for(const [x,z,part] of [[-.035,.05,3],[.035,-.08,3],[.035,.05,4],[-.035,-.08,4]]){g.set(COAT,part,0,[x,.055,z,0]);g.box(x-.016,0,z-.016,x+.016,.055,z+.016);}return g.geometry();}
  function iguanaGeometry(){const g=new NB(),gr=C('#4f8a3a');
    g.set(gr);g.box(-.025,0,-.06,.025,.03,.07);g.set(C('#8ab04a'));for(let k=0;k<5;k++)g.tri([0,.03,-.05+k*.025],[0,.03,-.03+k*.025],[0,.048,-.04+k*.025]);
    g.set(gr,7,0,[0,.02,.07,1]);g.box(-.02,.005,.065,.02,.035,.12);g.set(C('#c8a040'),7,0,[0,.02,.07,1]);g.tri([0,.005,.075],[0,.005,.11],[0,-.02,.085]);
    g.set(gr,2,0,[0,.012,-.06,.25]);g.beam([0,.012,-.06],[0,.01,-.16],.018);g.beam([0,.01,-.16],[.02,.006,-.26],.01);
    g.set(C('#3d6a2c'));for(const [x,z] of [[-.03,.05],[.03,.05],[-.03,-.04],[.03,-.04]])g.beam([x*.8,.012,z],[x*1.9,0,z+.015],.012);return g.geometry();}
  function heronGeometry(){const g=new NB(),w=C('#aab4bd');
    g.set(C('#6a6a60'));g.beam([-.012,0,0],[-.012,.11,-.005],.008);g.beam([.012,0,0],[.012,.11,-.005],.008);
    g.set(w);g.box(-.025,.1,-.07,.025,.15,.04);g.set(C('#8a96a2'));g.quad([-.026,.15,-.06],[.026,.15,-.06],[.02,.12,-.12],[-.02,.12,-.12]);
    g.set(w,7,0,[0,.14,.035,1]);g.beam([0,.14,.035],[0,.21,.05],.014);g.box(-.012,.205,.035,.012,.225,.07);g.set(C('#d8b040'),7,0,[0,.14,.035,1]);g.beam([0,.212,.07],[0,.206,.12],.008);return g.geometry();}
  function owlGeometry(){const g=new NB(),b=C('#6a5238');
    g.set(b);g.box(-.025,0,-.02,.025,.06,.025);g.set(b,7,0,[0,.06,0,0]);g.box(-.026,.058,-.02,.026,.1,.026);g.tri([-.024,.1,0],[-.012,.1,0],[-.022,.116,.004]);g.tri([.024,.1,0],[.012,.1,0],[.022,.116,.004]);
    g.set(C('#ffc93a'),7,1,[0,.06,0,0]);g.box(-.018,.075,.026,-.006,.087,.029);g.box(.006,.075,.026,.018,.087,.029);return g.geometry();}
  function robotGeometry(){const g=new NB();
    g.set(C('#d8dde4'));g.box(-.045,.025,-.06,.045,.085,.06);g.set(C('#9aa4b0'));g.box(-.04,.085,-.055,.04,.1,.055);
    g.set(C('#15181c'));for(const x of [-.05,.05])for(const z of [-.045,0,.045])g.box(x-.006,0,z-.018,x+.006,.036,z+.018);
    g.set(C('#62d8ff'),0,4);g.box(-.03,.05,.0605,.03,.065,.062);g.set(C('#30343a'));g.beam([.03,.1,-.04],[.03,.22,-.04],.006);
    g.set(C('#ff8a2a'),0,2,[0,0,0,.3]);g.box(.03,.215,-.05,.06,.235,-.04);return g.geometry();}
  function boatGeometry(){const g=new NB(),hull=[[-.09,.18,-.22],[.09,.18,-.22],[.09,.18,.12],[0,.18,.25],[-.09,.18,.12]],low=hull.map(([x,,z])=>[x*.7,.08,z*.9]);
    g.set(C('#e8e2d6'));for(let i=0;i<5;i++){const j=(i+1)%5;g.quad(hull[i],hull[j],low[j],low[i]);}g.set(C('#6a4a32'));g.tri(hull[0],hull[1],hull[2]);g.tri(hull[0],hull[2],hull[4]);g.tri(hull[4],hull[2],hull[3]);
    g.set(C('#3a4a5a'));g.box(-.06,.18,-.14,.06,.27,-.02);g.set(C('#20242a'));g.beam([0,.18,-.18],[0,.44,-.18],.012);
    g.set(C('#ffc070'),0,4);g.box(-.02,.44,-.2,.02,.48,-.16);g.set(C('#ff3a3a'),0,4);g.box(-.1,.19,.1,-.085,.205,.115);g.set(C('#3aff7a'),0,4);g.box(.085,.19,.1,.1,.205,.115);
    return g.geometry();}
  function partyBoatGeometry(){const g=new NB(),hw=.31,hl=.75;
    g.set(C('#1f2630'));g.box(-hw,.1,-hl,hw,.35,hl);g.set(C('#3a2f28'));g.box(-hw+.01,.35,-hl+.01,hw-.01,.355,hl-.01);
    g.set(C('#62e2c0'),0,4);g.box(-hw-.004,.3,-hl,-hw,.31,hl);g.box(hw,.3,-hl,hw+.004,.31,hl);
    g.set(C('#2a2f36'));for(const [x,z] of [[-hw+.02,-hl+.02],[hw-.02,-hl+.02],[-hw+.02,hl-.02],[hw-.02,hl-.02]])g.beam([x,.355,z],[x,.86,z],.02);
    for(const [a,b] of [[[-1,-1],[1,-1]],[[-1,1],[1,1]],[[-1,-1],[-1,1]],[[1,-1],[1,1]]])g.beam([a[0]*(hw-.02),.86,a[1]*(hl-.02)],[b[0]*(hw-.02),.86,b[1]*(hl-.02)],.02);
    g.set(C('#1a1e24'));g.box(-.12,.355,-hl+.04,.12,.5,-hl+.16);g.box(-hw+.04,.355,-hl+.04,-hw+.14,.62,-hl+.14);g.box(hw-.14,.355,-hl+.04,hw-.04,.62,-hl+.14);
    for(const [x0,z0,x1,z1] of [[-hw,-hl,-hw,hl],[hw,-hl,hw,hl],[-hw,-hl,hw,-hl],[-hw,hl,hw,hl]])for(let k=0;k<=12;k++){const f=k/12,x=x0+(x1-x0)*f,z=z0+(z1-z0)*f,y=.84-Math.sin(f*Math.PI)*.04;
      g.set(C(['#ffd060','#ff5fa2','#5ee6ff','#8cff6a','#ff8a3a'][k%5]),0,3,[0,0,0,(k*.618+x0*3.1+z0*1.7+5)%1]);g.box(x-.012,y-.012,z-.012,x+.012,y+.012,z+.012);}
    return g.geometry();}

  // ------------------------------------------------------------------ populations
  // Stratified ranks: any prefix (a lower tier) keeps the mix of the groups.
  const stratify=list=>{const keys=[];list.forEach((grp,gi)=>grp.forEach((e,j)=>keys.push([(j+.5)/grp.length,gi,e])));keys.sort((a,b)=>a[0]-b[0]||a[1]-b[1]);return keys.map(k=>k[2]);};
  const coats=['#b08a5a','#2a2420','#d8c8b0','#7a5a3a','#e8e0d4','#5a4a3a','#c09060','#3a302a'].map(h=>new THREE.Color().setRGB(...C(h)));
  // Dogs: street dogs roam the sidewalks, some sleep by the tiendas and food counters (C10.1).
  const dogRoutes=routes.map((r,i)=>[r,i]).filter(([r])=>r.district!=='core'&&r.kind!=='rim'&&!r.shared);
  const routeTotal=dogRoutes.reduce((s,[r])=>s+r.length,0),tiendas=venueList.filter(v=>v.type==='tienda'||v.type==='food'||v.type==='bakery');
  const sleepers=[],roamers=[];
  for(let i=0;i<6&&i<tiendas.length;i++){const v=tiendas[(i*5)%tiendas.length],p=v.face.clone().addScaledVector(v.normal,v.stand+.02).addScaledVector(v.right,(i%2?1:-1)*(v.width/2+.12));
    for(let k=0;k<8&&pointBlocked(V3.set(p.x,p.y+.05,p.z),.06,false);k++)p.addScaledVector(v.normal,.05);
    sleepers.push({mode:0,home:p,yaw:v.yaw+Math.PI/2});}
  for(let i=0,n=COUNTS.dog-sleepers.length;i<n;i++){let x=(i+.5)/n*routeTotal,pick=dogRoutes[0];for(const e of dogRoutes){if(x<e[0].length){pick=e;break;}x-=e[0].length;}
    const [r,ri]=pick,lane=Math.min(r.width/2+.04,r.clearance-.12);roamers.push({mode:1,route:ri,dist:x,dir:rnd()<.5?1:-1,offset:(rnd()<.5?1:-1)*(lane+(rnd()-.5)*.04),speed:.2+rnd()*.12,wait:rnd()*3,yaw:0});}
  const dogs=stratify([roamers,sleepers]);
  dogs.forEach(d=>{Object.assign(d,{x:0,y:0,z:0,phase:rnd()*TAU,cool:0,follow:-1,crumb:0,t:0,trail:new Float32Array(48*3),trailN:0,trailAcc:0,sniff:0,resume:d.mode});
    if(d.mode===0){d.x=d.home.x;d.y=d.home.y;d.z=d.home.z;}});
  const dogMesh=instancedOf(dogGeometry(),critterMat,dogs.length,[['aAnim',4]]);dogs.forEach((d,i)=>dogMesh.setColorAt(i,coats[i%coats.length]));
  // Cats sit on the ring rims (where the C6.5 rail runs), eyes glowing, heads turning to whoever passes.
  const cats=[];{const rimRoutes=routes.filter(r=>r.kind!=='rim'&&!r.shared&&r.district!=='episodic'&&r.district!=='core'),rail=SHORE.rail,reefRoute=routes[rail.route];
    for(let i=0;i<COUNTS.cat;i++){const r=rimRoutes[i%rimRoutes.length],p=DATA.plateaus[r.district],d=(i*7.31+rnd()*3)%r.length;
      for(let k=0;k<8;k++){const s=(d+k*.9)%r.length;
        if(r===reefRoute){const a=s/r.length*360;if((a>=rail.a0-8&&a<=rail.a1+8)||a+360<=rail.a1+8)continue;}
        let best=null;for(const side of [1,-1]){sampleRoute(r,s,V3,side*(r.width/2+.1));const out=Math.hypot(V3.x-p.cx,-V3.z-p.cy);if(!best||out>best[0])best=[out,V3.x,V3.y,V3.z];}
        cats.push({x:best[1],y:best[2]-.012,z:best[3],yaw:Math.atan2(best[1]-p.cx,best[3]+p.cy)+(rnd()-.5)*1.4,look:0,seed:rnd()});break;}}}
  const catMesh=instancedOf(catGeometry(),critterMat,cats.length,[['aAnim',4]]);cats.forEach((c,i)=>catMesh.setColorAt(i,coats[(i*3+1)%coats.length]));
  // Pigeons (C10.1, C8.10): one plaza flock of 15 in each of ten districts, pecking on open paving just inside a
  // walking lane, so the people and bikes on the lane scatter it. A site is clear of footprints, the carriageway,
  // the stage, venue fronts, furniture and trunks; the birds keep a bird's spacing and circle clear of the roofs.
  const FLOCK_DISTRICTS=['working','episodic','semantic','inbox','prospective','procedural','prasma','jhon','branding','core'];
  const PIGEON_GAP=.075;
  // Distance from (x, z) to the nearest carriageway edge of the district's routes, and that route's height.
  let gapRoute=null;
  function roadGap(x,z,d){let best=1e9;gapRoute=null;for(const r of routes){if(r.district!==d)continue;const h=r.width/2,pts=r.points;
    for(let i=0;i<pts.length;i++){const q=pts[i];if(Math.abs(q.x-x)>2||Math.abs(q.z-z)>2)continue;const g=Math.hypot(q.x-x,q.z-z)-h;if(g<best){best=g;gapRoute=r;}}}return best;}
  function onPlateau(x,z,d){const p=DATA.plateaus[d];if(p.shape==='disc')return Math.hypot(x-p.cx,-z-p.cy)<p.rx-.15;return Math.abs(x-p.cx)<p.rx-.15&&Math.abs(-z-p.cy)<p.ry-.15;}
  // Ground under a bird: the sidewalk (0.012 under the route) within 0.13 of the carriageway, else the plateau.
  const groundAt=(x,z,d)=>roadGap(x,z,d)<.13&&gapRoute?gapRoute.points[0].y-.012:DATA.plateaus[d].z;
  function flockLife(d){const st=stages.find(s=>s.district===d),keep=[];
    for(const f of furnitureItems)if(f.district===d)keep.push([f.world.x,f.world.z,.3]);
    for(const v of venueList)if(v.district===d)keep.push([v.face.x+v.normal.x*(v.terrace||0)/2,v.face.z+v.normal.z*(v.terrace||0)/2,v.length/2+(v.terrace||0)/2+.35]);
    for(const t of TREES)if(t.kind!=='balcony'&&t.world)keep.push([t.world.x,t.world.z,.28]);
    if(st)keep.push([st.center.x,st.center.z,st.r+.6]);
    return keep;}
  const clearOf=(keep,x,z,m)=>{for(let i=0;i<keep.length;i++){const k=keep[i];if(Math.abs(k[0]-x)<k[2]+m&&Math.abs(k[1]-z)<k[2]+m&&Math.hypot(k[0]-x,k[1]-z)<k[2]+m)return false;}return true;};
  const openGround=(x,z,d,r,keep,m)=>onPlateau(x,z,d)&&roadGap(x,z,d)>=.08+r&&!pointBlocked(V3.set(x,DATA.plateaus[d].z+.05,z),r,false)&&clearOf(keep,x,z,m);
  const RING8=[0,1,2,3,4,5,6,7].map(k=>[Math.cos(k/8*TAU)*.5,Math.sin(k/8*TAU)*.5]);
  const flocks=[];
  for(const d of FLOCK_DISTRICTS){const keep=flockLife(d);let best=null;
    for(const r of routes){if(r.district!==d||r.shared)continue;const edge=r.width/2+.13;
      for(let s=.25;s<r.length&&!(best&&best[0]===9);s+=.5)for(const side of [1,-1])for(const off of [.15,.4,.7]){
        sampleRoute(r,s,V4,side*(edge+off));const x=V4.x,z=V4.z;
        if(!openGround(x,z,d,.3,keep,.2))continue;
        let score=1;for(const [ox,oz] of RING8)if(openGround(x+ox,z+oz,d,.05,keep,.05))score++;
        if(!best||score>best[0])best=[score,x,z];}}
    if(!best)continue;
    // The widest circle the flock can fly round its site without touching a building.
    let rad=.35;for(const R of [1.3,1.1,.9,.7,.5]){let ok=true;
      for(let k=0;k<16&&ok;k++)for(const h of [.8,1.25,1.75])if(pointBlocked(V3.set(best[1]+Math.cos(k/16*TAU)*R,DATA.plateaus[d].z+h,best[2]+Math.sin(k/16*TAU)*R),.1,false)){ok=false;break;}
      if(ok){rad=R;break;}}
    flocks.push({x:best[1],y:groundAt(best[1],best[2],d),z:best[2],district:d,rad,keep,state:0,t:0,members:[]});}
  const pigeonGroups=flocks.map(()=>[]);
  for(let fi=0;fi<flocks.length;fi++){const f=flocks[fi],group=pigeonGroups[fi],n=Math.floor(COUNTS.pigeon/flocks.length)+(fi<COUNTS.pigeon%flocks.length?1:0);
    for(let j=0;j<n;j++){let x=f.x,z=f.z,ok=false;
      for(let k=0;k<80&&!ok;k++){const a=rnd()*TAU,r=.06+Math.sqrt(rnd())*(.45+k*.006);x=f.x+Math.cos(a)*r;z=f.z+Math.sin(a)*r;
        ok=openGround(x,z,f.district,.03,f.keep,0);for(let m=0;ok&&m<group.length;m++)if(Math.hypot(group[m].gx-x,group[m].gz-z)<PIGEON_GAP)ok=false;}
      if(!ok)break;
      const y=groundAt(x,z,f.district);
      group.push({flock:fi,gx:x,gy:y,gz:z,x,y,z,yaw:rnd()*TAU,peck:rnd()*TAU,ang:rnd()*TAU,rad:f.rad*(.55+.45*rnd()),hgt:.8+rnd()*.9,w:(rnd()<.5?1:-1)*(1.6+rnd()*.8),flap:rnd()*TAU});}
    delete f.keep;}
  const pigeons=stratify(pigeonGroups);pigeons.forEach((p,i)=>flocks[p.flock].members.push(i));
  const pigeonMesh=instancedOf(pigeonGeometry(),critterMat,pigeons.length,[['aAnim',4]]);pigeons.forEach((p,i)=>pigeonMesh.setColorAt(i,tint.setScalar(.8+rnd()*.4)));
  // Bats round the three tallest Downtown roofs and the Hills lamps.
  const bats=[];{const towers=nodes.filter(n=>n.district==='working').sort((a,b)=>b.h-a.h).slice(0,3),lamps=lifeLamps.filter(l=>l.route.district==='jhon');
    const groups=[[],[]],hillBats=lamps.length?16:0;
    for(let i=0;i<COUNTS.bat-hillBats;i++)groups[0].push({host:towers[i%3],r:.9+rnd()*1.3,up:.5+rnd()*1.6});
    for(let i=0;i<hillBats;i++)groups[1].push({lamp:lamps[(Math.floor(i/2)*Math.max(1,Math.floor(lamps.length/8)))%lamps.length],r:.35+rnd()*.35,up:.95+rnd()*.5});
    for(const b of stratify(groups))bats.push(Object.assign(b,{a:rnd()*TAU,w:(rnd()<.5?1:-1)*(1.6+rnd()*1.2),flap:rnd()*TAU,bob:rnd()*TAU}));}
  const batMesh=instancedOf(batGeometry(),critterMat,bats.length,[['aAnim',4]]);
  // Capybaras graze the lake shore in two families, unbothered; herons wade in the shallows.
  const tPier=shoreParam(PIER.x0,PIER.y0),tIsle=shoreParam(ISLE.x,ISLE.y),barSide=Math.sign(((shoreParam(SHORE.bar.x,SHORE.bar.y)-tPier+3*Math.PI)%TAU)-Math.PI)||1;
  const capybaras=[],herons=[];
  for(const [family,start] of [[0,tPier-barSide*1.15],[1,tIsle+.45]]){let t=start;
    for(let m=0;m<40;m++){shorePoint(t,.6,P2);if(sandFree(P2[0],P2[1],.35))break;t+=.05;}
    for(let j=0;j<3;j++){for(let m=0;m<20;m++){shorePoint(t+(j-1)*.07,.4+rnd()*.5,P3);if(sandFree(P3[0],P3[1],.15))break;}
      capybaras.push({hx:P3[0],hy:P3[1],x:P3[0],y:P3[1],tx:P3[0],ty:P3[1],yaw:rnd()*TAU,wait:rnd()*6,graze:rnd()*TAU,family});}}
  const capyMesh=instancedOf(capybaraGeometry(),critterMat,capybaras.length,[['aAnim',4]]);capybaras.forEach((c,i)=>capyMesh.setColorAt(i,tint.setRGB(...C(i%3?'#8a5a36':'#7a4e2e'))));
  for(const t of [tPier-barSide*2.2,tIsle-.5]){shorePoint(t,-.12,P2);const n=shorePoint(t+.01,-.12,[0,0]);herons.push({x:P2[0],y:P2[1],yaw:Math.atan2(n[0]-P2[0],-(n[1]-P2[1])),strike:rnd()*10});}
  const heronMesh=instancedOf(heronGeometry(),critterMat,herons.length,[['aAnim',4]]);
  // Iguanas on the Hills palms, the lake trees at the Reef and the Hills house walls; owls in the Hills palms.
  const hillPalms=palms.filter(t=>t.at==='hills'),lakeTrunks=[...broad,...palms.filter(t=>t.at==='lake')],iguanas=[],wallIguanas=[],owls=[];
  for(let i=0;i<4&&i<hillPalms.length;i++){const t=hillPalms[(i*7+3)%hillPalms.length],a=rnd()*TAU;iguanas.push({x:t.world.x+Math.sin(a)*.06,y:t.world.y+1.1+rnd()*1.4,z:t.world.z+Math.cos(a)*.06,yaw:a,pitch:-Math.PI/2});}
  for(let i=0;i<3&&i<lakeTrunks.length;i++){const t=lakeTrunks[(i*5+1)%lakeTrunks.length],a=rnd()*TAU,r=t.kind==='tropical'?.07:.06;iguanas.push({x:t.world.x+Math.sin(a)*r,y:t.world.y+.3+rnd()*.3,z:t.world.z+Math.cos(a)*r,yaw:a,pitch:-Math.PI/2});}
  for(let i=0;i<3&&i<balconies.length;i++){const b=balconies[(i*11+2)%balconies.length],w={balcony:b,x:b.x,y:0,z:-b.y,yaw:yaw3(b.rot),pitch:-Math.PI/2,dirty:true};wallIguanas.push(w);iguanas.push(w);}
  for(let i=0;i<COUNTS.owl&&i<hillPalms.length;i++){const t=hillPalms[(i*9+5)%hillPalms.length];owls.push({x:t.top.x+.07,y:t.top.y-.04,z:t.top.z,yaw:rnd()*TAU,look:0,seed:rnd()});}
  const iguanaMesh=instancedOf(iguanaGeometry(),critterMat,iguanas.length,[['aAnim',4]]),owlMesh=instancedOf(owlGeometry(),critterMat,owls.length,[['aAnim',4]]);
  // Delivery robots roll round the Dome ring (C10.1).
  const domeRoute=routes.findIndex(r=>r.district==='onebrain'),robots=[];
  for(let i=0;i<COUNTS.robot;i++){const r=routes[domeRoute];robots.push({dist:i/COUNTS.robot*r.length,offset:(i%2?1:-1)*Math.min(r.width/2+.06,r.clearance-.12),dir:i%2?1:-1,wait:rnd()*4,speed:.22+rnd()*.08});}
  const robotMesh=instancedOf(robotGeometry(),critterMat,robots.length,[['aAnim',4]]);

  // ------------------------------------------------------------------ boats (C9.3): loops in lake coordinates
  // The island sits at v = -1 and the pier runs to the Reef at +v, so the loops keep to the two long lobes
  // and the near-side corners, clear of the island beach, the pier and each other. The party boat circles its
  // lobe at 0.4 units/s.
  const PATHS=[[-5.2,.8,1.5,1.5,.3],[-4.6,-3.3,.9,.9,.26],[-4.2,3.8,.9,.9,.24],[5.4,-.3,2.4,3,.4]];
  const boats=PATHS.map(([cu,cv,a,b,speed],k)=>{boatPaths[k].set(cu,cv,a,b);return {cu,cv,a,b,speed,theta:k*1.7,dir:k%2?-1:1,x:0,y:0,z:0,yaw:0,bob:0,party:k===3};});
  const boatMesh=instancedOf(boatGeometry(),critterMat,3,[['aAnim',4]]),partyMesh=instancedOf(partyBoatGeometry(),critterMat,1,[['aAnim',4]]);
  boatMesh.setColorAt(1,tint.setRGB(...C('#d8e8ff')));boatMesh.setColorAt(2,tint.setRGB(...C('#ffe8c8')));
  function boatPose(b){const u=b.cu+b.a*Math.cos(b.theta),v=b.cv+b.b*Math.sin(b.theta);fromLocal(u,v,P2);b.x=P2[0];b.z=-P2[1];
    fromLocal(u-b.a*Math.sin(b.theta)*b.dir*.1,v+b.b*Math.cos(b.theta)*b.dir*.1,P3);b.yaw=Math.atan2(P3[0]-P2[0],-(P3[1]-P2[1]));}

  // ------------------------------------------------------------------ fish and jellies (C9.3): they glow under the surface
  const glowUniforms={uTime:U.uTime,uBeat:U.uBeat,uLive:{value:reduced?0:1}};
  const fishGeo=new THREE.BufferGeometry();fishGeo.setAttribute('position',new THREE.Float32BufferAttribute([-.5,0,-.5,.5,0,-.5,.5,0,.5,-.5,0,-.5,.5,0,.5,-.5,0,.5],3));
  fishGeo.setAttribute('uv',new THREE.Float32BufferAttribute([0,0,1,0,1,1,0,0,1,1,0,1],2));
  const fishMat=new THREE.ShaderMaterial({uniforms:glowUniforms,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,side:THREE.DoubleSide,
    vertexShader:`varying vec2 vUv;varying vec3 vColor;varying float vSeed;void main(){vUv=uv;vColor=instanceColor;vSeed=instanceMatrix[3].x*3.7+instanceMatrix[3].z*1.3;gl_Position=projectionMatrix*modelViewMatrix*instanceMatrix*vec4(position,1.0);}`,
    fragmentShader:`varying vec2 vUv;varying vec3 vColor;varying float vSeed;uniform float uTime;void main(){vec2 q=vUv*2.0-1.0;q.x+=sin(uTime*9.0+vSeed-q.y*3.0)*.12*(1.0-q.y)*.5;
      float body=exp(-(q.x*q.x*14.0+(q.y-.15)*(q.y-.15)*2.2)),tail=exp(-((q.y+.75)*(q.y+.75)*20.0+q.x*q.x*4.0))*.7;gl_FragColor=vec4(vColor*(body+tail),1.0);
      #include <colorspace_fragment>
    }`});
  const fish=[],SCHOOLS=[[-5,-.5,2.2,2.4,.16],[5,-.5,2.2,2.4,-.15],[0,-4.8,2.6,.6,.12],[3.6,3.8,1.4,1,-.2],[-3.6,3.8,1.4,1,.18]];
  const fishColors=['#5ee6ff','#62e2c0','#ff7ab6','#ffd060','#a0ff8a'].map(h=>new THREE.Color().setRGB(...C(h)));
  for(let i=0;i<COUNTS.fish;i++){const s=i%SCHOOLS.length;fish.push({school:s,off:(Math.floor(i/SCHOOLS.length)-6)*.09+(rnd()-.5)*.05,r:1+(rnd()-.5)*.18,y:WATER_Y-.02-rnd()*.05,wob:rnd()*TAU,size:.8+rnd()*.5});}
  const fishMesh=new THREE.InstancedMesh(fishGeo,fishMat,fish.length);fishMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);fishMesh.frustumCulled=false;
  fish.forEach((f,i)=>fishMesh.setColorAt(i,fishColors[f.school].clone().multiplyScalar(.8+rnd()*.4)));group.add(fishMesh);
  const jellyGeo=(()=>{const bell=new THREE.SphereGeometry(1,10,5,0,TAU,0,Math.PI/2).toNonIndexed(),p=[...bell.attributes.position.array],n=[...bell.attributes.normal.array],k=p.map(()=>0).slice(0,p.length/3);
    for(let t=0;t<6;t++){const a=t/6*TAU,x=Math.cos(a)*.55,z=Math.sin(a)*.55;for(let s=0;s<4;s++){const y0=-s*.45,y1=-(s+1)*.45,w=.06;
      p.push(x-w,y0,z,x+w,y0,z,x+w,y1,z,x-w,y0,z,x+w,y1,z,x-w,y1,z);for(let j=0;j<6;j++){n.push(0,0,1);k.push(s+1);}}}
    const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(p,3));g.setAttribute('normal',new THREE.Float32BufferAttribute(n,3));g.setAttribute('aTent',new THREE.Float32BufferAttribute(k,1));bell.dispose();return g;})();
  const jellyMat=new THREE.ShaderMaterial({uniforms:glowUniforms,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,side:THREE.DoubleSide,
    vertexShader:`attribute float aTent;uniform float uBeat,uTime,uLive;varying vec3 vColor;varying float vRim,vTent,vDepth;
      void main(){float sq=uLive*pow(1.0-fract(uBeat),3.0);vec3 p=position;float seed=instanceMatrix[3].x*2.1+instanceMatrix[3].z;
        if(aTent<.5){p.xz*=1.0-.24*sq;p.y*=1.0+.16*sq;}else{p.x+=sin(uTime*1.6+aTent*1.3+seed)*.12*aTent;p.z+=cos(uTime*1.3+aTent+seed)*.1*aTent;p.y+=sq*.12;}
        vec4 w=modelMatrix*instanceMatrix*vec4(p,1.0);vDepth=w.y;vec3 N=normalize(mat3(modelMatrix)*mat3(instanceMatrix)*normal),V=normalize(cameraPosition-w.xyz);
        vRim=1.0-abs(dot(N,V));vTent=aTent;vColor=instanceColor*(.7+.5*sq);gl_Position=projectionMatrix*viewMatrix*w;}`,
    fragmentShader:`varying vec3 vColor;varying float vRim,vTent,vDepth;void main(){float fade=exp(-max(0.0,${WATER_Y.toFixed(3)}-vDepth)*7.0);
      float a=vTent<.5?.12+.9*pow(vRim,2.0):.35*(1.0-vTent*.2);gl_FragColor=vec4(vColor*a*fade,1.0);
      #include <colorspace_fragment>
    }`});
  const jellies=[],jellyColors=['#ff7ad8','#b27aff','#62d8ff','#ffb0e0'].map(h=>new THREE.Color().setRGB(...C(h)));
  for(let i=0;i<COUNTS.jelly;i++){for(let k=0;k<40;k++){fromLocal((rnd()*2-1)*(AX-1.2),(rnd()*2-1)*(BY-1.2),P2);
      if(shoreGap(P2[0],P2[1])<=-.9&&Math.hypot(P2[0]-ISLE.x,P2[1]-ISLE.y)>=BEACH_R+.5&&pierGap(P2[0],P2[1])>=.6)break;}
    jellies.push({ax:P2[0],az:-P2[1],y:WATER_Y-.07-rnd()*.1,ph:rnd()*TAU,r:.15+rnd()*.25,s:.035+rnd()*.03});}
  const jellyMesh=new THREE.InstancedMesh(jellyGeo,jellyMat,jellies.length);jellyMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);jellyMesh.frustumCulled=false;
  jellies.forEach((j,i)=>jellyMesh.setColorAt(i,jellyColors[i%4].clone().multiplyScalar(.8)));group.add(jellyMesh);

  // ------------------------------------------------------------------ fireflies over the lake and the Hills gardens; the bonfire flames
  const flyAnchors=[],flySeeds=[];
  {const lakeFlies=[],hillFlies=[],hp=DATA.plateaus.jhon;
    for(let i=0;lakeFlies.length<250&&i<4000;i++){shorePoint(rnd()*TAU,-1+rnd()*2.6,P2);const s=surfaceAt(P2[0],-P2[1]);if(s===undefined||(s===null&&!isWater(P2[0],-P2[1])))continue;lakeFlies.push([P2[0],(s??WATER_Y)+.18+rnd()*.8,-P2[1]]);}
    for(let i=0;hillFlies.length<150&&i<4000;i++){const a=rnd()*TAU,r=Math.sqrt(rnd())*(hp.rx-.4),x=hp.cx+Math.cos(a)*r,z=-(hp.cy+Math.sin(a)*r);
      if(pointBlocked(V3.set(x,hp.z+.5,z),.45,false))continue;hillFlies.push([x,hp.z+.2+rnd()*.9,z]);}
    for(const f of stratify([lakeFlies,hillFlies])){flyAnchors.push(...f);flySeeds.push(rnd());}}
  const flyGeo=new THREE.BufferGeometry();flyGeo.setAttribute('position',new THREE.Float32BufferAttribute(flyAnchors,3));flyGeo.setAttribute('aSeed',new THREE.Float32BufferAttribute(flySeeds,1));
  const fireflies=new THREE.Points(flyGeo,new THREE.ShaderMaterial({uniforms:glowUniforms,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    vertexShader:`attribute float aSeed;uniform float uTime;varying float vOn;void main(){vec3 p=position+vec3(sin(uTime*.37+aSeed*40.0),sin(uTime*.29+aSeed*17.0)*.5,cos(uTime*.31+aSeed*23.0))*.22;
      vOn=.15+.85*smoothstep(.55,1.0,sin(uTime*(.9+aSeed*1.4)+aSeed*60.0));vec4 mv=modelViewMatrix*vec4(p,1.0);gl_Position=projectionMatrix*mv;gl_PointSize=clamp(28.0/-mv.z,1.2,4.0);}`,
    fragmentShader:`varying float vOn;void main(){float r=length(gl_PointCoord-.5);if(r>.5)discard;gl_FragColor=vec4(vec3(.78,1.0,.35)*vOn*(1.0-r*2.0),1.0);
      #include <colorspace_fragment>
    }`}));fireflies.frustumCulled=false;group.add(fireflies);
  const flamePos=[],flameKind=[];
  if(SHORE.bonfire){const f=W(SHORE.bonfire.x,SHORE.bonfire.y,SHORE.bonfire.z);for(let k=0;k<5;k++){flamePos.push(f.x+(k-2)*.025,f.y+.08+(k%2)*.02,f.z+((k*3)%5-2)*.02);flameKind.push(k/5);}
    for(let k=0;k<26;k++){flamePos.push(f.x+(rnd()-.5)*.14,f.y+.05,f.z+(rnd()-.5)*.14);flameKind.push(1+rnd());}}
  const flameGeo=new THREE.BufferGeometry();flameGeo.setAttribute('position',new THREE.Float32BufferAttribute(flamePos.length?flamePos:[0,-10,0],3));flameGeo.setAttribute('aKind',new THREE.Float32BufferAttribute(flameKind.length?flameKind:[0],1));
  const flames=new THREE.Points(flameGeo,new THREE.ShaderMaterial({uniforms:glowUniforms,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    vertexShader:`attribute float aKind;uniform float uTime;varying float vKind,vFade;void main(){vec3 p=position;vKind=aKind;vFade=1.0;
      if(aKind<1.0){p.y+=sin(uTime*11.0+aKind*20.0)*.012;}else{float t=fract(uTime*.35+aKind*7.13);p.y+=t*1.1;p.x+=sin(t*9.0+aKind*30.0)*.08;vFade=1.0-t;}
      vec4 mv=modelViewMatrix*vec4(p,1.0);gl_Position=projectionMatrix*mv;gl_PointSize=aKind<1.0?clamp(220.0/-mv.z*(1.0+.2*sin(uTime*13.0+aKind*9.0)),2.0,160.0):clamp(14.0/-mv.z,1.0,3.0);}`,
    fragmentShader:`varying float vKind,vFade;void main(){vec2 q=gl_PointCoord-.5;vec3 c;if(vKind<1.0){float h=.5-q.y,w=abs(q.x)*(1.3+h*2.4);float a=(1.0-smoothstep(.12,.5,w))*smoothstep(0.0,.12,h)*(1.0-smoothstep(.45,1.0,h));
      c=mix(vec3(1.0,.32,.05),vec3(1.0,.85,.45),(1.0-h)*(1.0-w*2.0))*a*.75;}else{if(length(q)>.5)discard;c=vec3(1.0,.5,.15)*vFade;}gl_FragColor=vec4(c,1.0);
      #include <colorspace_fragment>
    }`}));flames.frustumCulled=false;group.add(flames);

  // ------------------------------------------------------------------ people the lake adds (crowd.js kind 3)
  // Revellers on the party boat, strollers on the wet sand, the bartender, a patron and folk round the fire.
  // They are others (C3.7): crowd.js reserves their share of each tier's extras cap (reserve, below), so the
  // venue extras give way and the others stay within 88/53/20. Each one's gate() applies the lake's tier count.
  const extras=[],capOf=k=>()=>LAKE_PEOPLE[k][tier.current]||0,riderCap=capOf('riders'),strollCap=capOf('strollers'),folkCap=capOf('shoreFolk');
  const reserve={};for(const t of [1,2,3])reserve[t]=LAKE_PEOPLE.riders[t]+LAKE_PEOPLE.strollers[t]+LAKE_PEOPLE.shoreFolk[t];
  const party=boats[3],DECK=.355;
  for(let k=0;k<LAKE_PEOPLE.riders[3];k++){const dj=k===0,lx=dj?0:((k-1)%3-1)*.17,lz=dj?-.5:-.24+Math.floor((k-1)/3)*.21,turn=dj?0:Math.PI*(k%2?.85:1.15);
    extras.push({lake:'rider',pose:'ride',style:dj?'dj':['wave','bounce','handsup','baile'][k%4],energy:.9,district:'reef',x:0,y:0,z:0,yaw:0,extraRank:-1,free:true,aboard:true,
      gate:()=>k<riderCap(),follow(p,out){const c=Math.cos(party.yaw),s=Math.sin(party.yaw);out.set(party.x+c*lx+s*lz,party.y+DECK,party.z-s*lx+c*lz);p.yawNow=party.yaw+turn;}});}
  // The stroll path: the wet sand 0.25 from the water, clear of the pier, the bar, the fire, the trees and the Reef ring.
  const STROLL_G=.25,strollT=[];for(let i=0;i<720;i++){const t=i/720*TAU;shorePoint(t,STROLL_G,P2);if(sandFree(P2[0],P2[1],.35,.12))strollT.push(t);}
  const arcs=[];{let start=null;for(let i=0;i<strollT.length;i++){if(start===null)start=strollT[i];const next=strollT[i+1];if(next===undefined||next-strollT[i]>TAU/700){arcs.push([start,strollT[i]]);start=null;}}}
  arcs.sort((a,b)=>(b[1]-b[0])-(a[1]-a[0]));
  const strollers=[];
  for(let k=0;k<LAKE_PEOPLE.strollers[3]&&arcs.length;k++){const arc=arcs[k%Math.min(2,arcs.length)],len=arc[1]-arc[0],span=Math.min(len,.35+rnd()*.5),t0=arc[0]+rnd()*(len-span);
    const st={t0,t1:t0+span,t:t0+rnd()*span,dir:rnd()<.5?1:-1,x:0,z:0,speed:.21};strollers.push(st);
    extras.push({lake:'stroller',pose:'walk',relaxed:false,district:'reef',x:0,y:0,z:0,yaw:0,extraRank:-1,free:true,stroller:st,gate:()=>k<strollCap(),
      follow(p,out){shorePoint(st.t,STROLL_G,P3);out.set(P3[0],sandHeight(P3[0],P3[1],STROLL_G)+.004,-P3[1]);shorePoint(st.t+st.dir*.02,STROLL_G,P2);p.yawNow=Math.atan2(P2[0]-P3[0],-(P2[1]-P3[1]));st.x=P3[0];st.z=-P3[1];}});}
  {const b=SHORE.bar,bc=W(b.x,b.y,b.z),by=yaw3(b.rot),cb=Math.cos(by),sb=Math.sin(by),at=(x,z)=>[bc.x+x*cb+z*sb,bc.z-x*sb+z*cb];
    // In tier order: the bartender, someone on a log by the fire, a patron at the counter, a second log.
    const seats=[];
    if(SHORE.bonfire){const f=W(SHORE.bonfire.x,SHORE.bonfire.y,SHORE.bonfire.z);for(let k=0;k<2;k++){const a=k/3*TAU+.4,x=f.x+Math.cos(a)*.36,z=f.z+Math.sin(a)*.36;
      seats.push([[x,z],'sit',k===1?7:undefined,null,Math.atan2(f.x-x,f.z-z),(surfaceAt(x,z)??f.y)+.02]);}}
    const folk=[[at(0,.05),'vend',8,'bar',by,bc.y+.04],seats[0],[at(-.22,.4),'queue',undefined,null,by+Math.PI,bc.y+.04],seats[1]].filter(Boolean).slice(0,LAKE_PEOPLE.shoreFolk[3]);
    folk.forEach(([p,pose,archetype,job,yaw,y],k)=>extras.push({lake:'folk',pose,archetype,job:job||undefined,bottle:pose!=='vend',district:'reef',x:p[0],y,z:p[1],yaw,extraRank:-1,free:true,gate:()=>k<folkCap()}));}

  // ------------------------------------------------------------------ movers: the visitor and every bike (hook)
  // explore.js, the tour and the NPC light cycles call nature.mover(slot, x, y, z, bike) each frame with the
  // ground position under the visitor or the wheels (slot 0 visitor, 1 to 12 cycles); the ride camera is slot 13.
  // Slots 14 to 20 are reserved for simultaneous scripted mover checks. Pigeons scatter from any mover, dogs follow bikes,
  // cats and owls turn their heads, the shallows glow where a mover walks the shore.
  const MOVERS=21,moverPos=new Float32Array(MOVERS*3),moverFrame=new Int32Array(MOVERS).fill(-9),moverBike=new Uint8Array(MOVERS),moverSince=new Float64Array(MOVERS),crumbs=new Float32Array(MOVERS*80);
  let frameNo=0,crumbClock=0,anyMover=false;const diagnostics={dogFollows:0,flockScatters:0,flockLandings:0};
  const moverLive=s=>frameNo-moverFrame[s]<=2;
  function mover(slot,x,y,z,bike=true){if(!(slot>=0&&slot<MOVERS))return;if(!moverLive(slot))moverSince[slot]=crumbClock;
    moverPos[slot*3]=x;moverPos[slot*3+1]=y;moverPos[slot*3+2]=z;moverBike[slot]=bike?1:0;moverFrame[slot]=frameNo;}
  function nearestMover(x,z,range,bikes){if(!anyMover)return -1;let best=-1,bd=range*range;
    for(let s=0;s<MOVERS;s++){if(!moverLive(s)||(bikes&&!moverBike[s]))continue;const dx=moverPos[s*3]-x,dz=moverPos[s*3+2]-z,d=dx*dx+dz*dz;if(d<bd){bd=d;best=s;}}return best;}
  // A mover's breadcrumbs: one per 0.05 s of the nature clock, the last second kept. A crumb is addressed by its
  // window index. The current window holds this frame's position; an older one holds a real position only if the
  // mover was already live when that window began.
  const crumbWindow=()=>Math.floor(crumbClock/.05);
  const crumbKept=(slot,w)=>w===crumbWindow()||(w>=Math.ceil(moverSince[slot]/.05-1e-6)&&w<crumbWindow()&&w>crumbWindow()-19);
  function crumbOf(slot,w,out){const o=slot*80+((w%20)+20)%20*4;return out.set(crumbs[o],crumbs[o+1],crumbs[o+2]);}
  // The crumb of `slot` nearest to (x, z): where a dog joins the bike's path.
  function nearestCrumb(slot,x,z){let best=crumbWindow(),bd=1e9;for(let w=crumbWindow();crumbKept(slot,w);w--){const o=slot*80+((w%20)+20)%20*4,d=(crumbs[o]-x)**2+(crumbs[o+2]-z)**2;if(d<bd){bd=d;best=w;}}return best;}

  // ------------------------------------------------------------------ tier
  const meshes={dog:dogMesh,cat:catMesh,pigeon:pigeonMesh,bat:batMesh,capybara:capyMesh,iguana:iguanaMesh,heron:heronMesh,owl:owlMesh,robot:robotMesh,fish:fishMesh,jelly:jellyMesh,boat:boatMesh,partyBoat:partyMesh};
  const meshList=Object.values(meshes),animList=meshList.map(m=>m.geometry.attributes.aAnim).filter(Boolean);
  const allocated={dog:dogs.length,cat:cats.length,pigeon:pigeons.length,bat:bats.length,capybara:capybaras.length,iguana:iguanas.length,heron:herons.length,owl:owls.length,robot:robots.length,fish:fish.length,jelly:jellies.length,boat:3,partyBoat:1};
  let currentTier=-1;
  function applyTier(t){currentTier=t;for(const k in meshes)meshes[k].count=Math.min(allocated[k],tierCount(COUNTS[k],t));flyGeo.setDrawRange(0,Math.min(flyAnchors.length/3,tierCount(COUNTS.firefly,t)));
    for(let k=0;k<3;k++)boatState[k].z=0;}
  applyTier(tier.current);

  // ------------------------------------------------------------------ the frame
  let clock=0;const an={dog:dogMesh,cat:catMesh,pigeon:pigeonMesh,bat:batMesh,capybara:capyMesh,iguana:iguanaMesh,heron:heronMesh,owl:owlMesh};
  for(const k in an)an[k]=an[k].geometry.attributes.aAnim.array;
  const setAnim=(a,i,x,y,z,w)=>{const o=i*4;a[o]=x;a[o+1]=y;a[o+2]=z;a[o+3]=w;};
  let balconyWeek=-1;
  function placeBalconies(){
    if(balconyWeek===state.t)return;balconyWeek=state.t;
    const arr=balconyMesh.instanceMatrix.array;
    for(let i=0;i<balconies.length;i++){const t=balconies[i],n=t.node;if(!n||n.state==='absent'){hideAt(arr,i);continue;}
      put(arr,i,t.x,plateauZ(n.district)+t.f*n.h*(n.rise??1),-t.y,yaw3(t.rot),t.w,1,1,0,0);}
    balconyMesh.instanceMatrix.needsUpdate=true;
    for(let i=0;i<wallIguanas.length;i++)wallIguanas[i].dirty=true;
  }
  function updateDogs(dt,live){
    const arr=dogMesh.instanceMatrix.array,a=an.dog;
    for(let i=0;i<dogMesh.count;i++){const d=dogs[i];d.cool=Math.max(0,d.cool-dt);
      if(d.mode<2&&d.cool<=0&&live){const s=nearestMover(d.x,d.z,1.5,true);if(s>=0){d.resume=d.mode;d.mode=2;d.follow=s;d.t=0;d.trailN=0;d.trailAcc=0;d.crumb=nearestCrumb(s,d.x,d.z);diagnostics.dogFollows++;}}
      let gait=0;
      if(d.mode===1){
        if(d.wait>0){d.wait-=dt;d.sniff=Math.min(1,d.sniff+dt*2);}else{d.sniff=Math.max(0,d.sniff-dt*3);d.dist+=d.dir*d.speed*dt;gait=live?d.speed:0;if(rnd()<dt*.12)d.wait=1+rnd()*3;if(rnd()<dt*.03)d.dir*=-1;}
        const r=routes[d.route];sampleRoute(r,d.dist,V3,d.offset);sampleRoute(r,d.dist+d.dir*.12,V4,d.offset);d.x=V3.x;d.y=V3.y+.004;d.z=V3.z;d.yaw=Math.atan2(V4.x-V3.x,V4.z-V3.z);
      } else if(d.mode===2){
        // Follow the bike along its own path, crumb by crumb in order and at least 0.35 s behind it, for 2 s at
        // most, recording the way back. A dog never cuts a bend: a bike that outruns the kept crumbs, or a step
        // that would enter a footprint or leave the ground, ends the chase.
        d.t+=dt;const newest=crumbWindow()-7;
        while(d.crumb<newest&&crumbKept(d.follow,d.crumb+1)){crumbOf(d.follow,d.crumb,V4);if(Math.hypot(V4.x-d.x,V4.z-d.z)>.12)break;d.crumb++;}
        let chase=d.t<2&&moverLive(d.follow)&&crumbKept(d.follow,d.crumb);
        if(chase){crumbOf(d.follow,d.crumb,V4);const dx=V4.x-d.x,dz=V4.z-d.z,dist=Math.hypot(dx,dz),step=Math.min(dist,2.2*dt);
          if(dist>2.5)chase=false;
          else if(dist>.02){const nx=d.x+dx/dist*step,nz=d.z+dz/dist*step;
            if(pointBlocked(V3.set(nx,d.y+.05,nz),.05,true)||surfaceAt(nx,nz)===null)chase=false;
            else{d.x=nx;d.z=nz;d.y+=(V4.y-d.y)*Math.min(1,dt*8);d.yaw=Math.atan2(dx,dz);gait=step/Math.max(dt,1e-3);}}}
        d.trailAcc+=dt;if(d.trailAcc>=.05&&d.trailN<48){d.trailAcc=0;const o=d.trailN*3;d.trail[o]=d.x;d.trail[o+1]=d.y;d.trail[o+2]=d.z;d.trailN++;}
        if(!chase)d.mode=3;
      } else if(d.mode===3){
        // Walk back along its own trail to where it left its street, then carry on.
        if(d.trailN>0){const o=(d.trailN-1)*3,dx=d.trail[o]-d.x,dz=d.trail[o+2]-d.z,dist=Math.hypot(dx,dz),step=1.4*dt;
          if(dist<=step){d.x=d.trail[o];d.y=d.trail[o+1];d.z=d.trail[o+2];d.trailN--;}else{d.x+=dx/dist*step;d.z+=dz/dist*step;d.yaw=Math.atan2(dx,dz);}gait=1.4;}
        else{d.mode=d.resume;d.cool=5;if(d.mode===0){d.x=d.home.x;d.y=d.home.y;d.z=d.home.z;}}
      }
      const lying=d.mode===0;
      if(live)d.phase+=dt*gait*38;
      put(arr,i,d.x,d.y-(lying?.035:0),d.z,d.yaw,1.15,lying?.55:1.15,1.15,lying?0:.12*d.sniff,0);
      setAnim(a,i,d.phase,lying?0:Math.min(.7,gait*2.2),lying?.05:.55,0);
    }
  }
  function updatePigeons(dt,live){
    const arr=pigeonMesh.instanceMatrix.array,a=an.pigeon,BAR=beat.barSeconds;
    for(let fi=0;fi<flocks.length;fi++){const f=flocks[fi];f.t+=dt;
      if(f.state===0&&live&&anyMover){for(let m=0;m<f.members.length;m++){const i=f.members[m];if(i>=pigeonMesh.count)continue;const p=pigeons[i];if(nearestMover(p.x,p.z,1.5,false)>=0){f.state=1;f.t=0;diagnostics.flockScatters++;break;}}}
      else if(f.state===1&&f.t>=2*BAR+.8){if(nearestMover(f.x,f.z,2.2,false)>=0)f.t-=BAR;else{f.state=0;diagnostics.flockLandings++;}}}
    for(let i=0;i<pigeonMesh.count;i++){const p=pigeons[i],f=flocks[p.flock];
      if(f.state===1){if(live)p.ang+=p.w*dt*.9;const up=Math.min(1,f.t/.5),down=Math.max(0,Math.min(1,(f.t-2*BAR)/.8)),lift=up*(1-down);
        const tx=p.gx+(f.x+Math.cos(p.ang)*p.rad-p.gx)*lift,tz=p.gz+(f.z+Math.sin(p.ang)*p.rad-p.gz)*lift,ty=p.gy+p.hgt*Math.sin(lift*Math.PI/2);
        if(Math.abs(tx-p.x)+Math.abs(tz-p.z)>1e-5)p.yaw=Math.atan2(tx-p.x,tz-p.z);p.x=tx;p.y=ty;p.z=tz;if(live)p.flap+=dt*38;setAnim(a,i,p.flap,0,lift>.02?1.1:0,0);}
      else{p.x=p.gx;p.y=p.gy;p.z=p.gz;if(live){p.peck+=dt*(3+(i%5));if(rnd()<dt*.15)p.yaw+=(rnd()-.5)*1.5;}setAnim(a,i,0,0,0,.5*Math.max(0,Math.sin(p.peck))*(i%3?1:0));}
      put(arr,i,p.x,p.y,p.z,p.yaw,1,1,1,0,0);}
  }
  function update(dt){
    frameNo++;const live=!reduced;
    if(tier.current!==currentTier)applyTier(tier.current);
    clock+=dt;crumbClock+=dt;
    // The ride camera floats above the road, so it scatters pigeons but no dog chases it; the V5 tour bike
    // and explore.js pass their ground position with bike=true.
    if(state.ride>=0)mover(13,camera.position.x,camera.position.y,camera.position.z,false);
    anyMover=false;for(let s=0;s<MOVERS;s++)if(moverLive(s))anyMover=true;
    {const k=Math.floor(crumbClock/.05)%20;for(let s=0;s<MOVERS;s++){const o=s*80+k*4;crumbs[o]=moverPos[s*3];crumbs[o+1]=moverPos[s*3+1];crumbs[o+2]=moverPos[s*3+2];}}
    placeBalconies();
    const barPhase=beat.now().barPhase;
    updateDogs(dt,live);
    {const arr=catMesh.instanceMatrix.array,a=an.cat;for(let i=0;i<catMesh.count;i++){const c=cats[i],s=nearestMover(c.x,c.z,2.5,false);
      const want=s>=0?Math.atan2(moverPos[s*3]-c.x,moverPos[s*3+2]-c.z)-c.yaw:Math.sin(clock*.2+c.seed*9)*.8,w=Math.atan2(Math.sin(want),Math.cos(want));
      c.look+=(Math.max(-1.2,Math.min(1.2,w))-c.look)*Math.min(1,dt*3);put(arr,i,c.x,c.y,c.z,c.yaw,1.1,1.1,1.1,0,0);setAnim(a,i,0,0,.35,c.look);}}
    updatePigeons(dt,live);
    {const arr=batMesh.instanceMatrix.array,a=an.bat;for(let i=0;i<batMesh.count;i++){const t=bats[i];let cx,cy,cz;
      if(t.host){if(t.host.state==='absent'){hideAt(arr,i);continue;}cx=t.host.x;cz=-t.host.y;cy=plateauZ(t.host.district)+t.host.h*(t.host.rise??1)+t.up;}else{cx=t.lamp.p.x;cz=t.lamp.p.z;cy=t.lamp.p.y+t.up;}
      if(live){t.a+=t.w*dt;t.flap+=dt*70;}const r=t.r*(1+.25*Math.sin(t.a*1.7+t.bob)),sg=Math.sign(t.w);
      put(arr,i,cx+Math.cos(t.a)*r,cy+Math.sin(t.a*2.3+t.bob)*.18,cz+Math.sin(t.a)*r,Math.atan2(-Math.sin(t.a)*sg,Math.cos(t.a)*sg),1.3,1.3,1.3,0,sg*.4);setAnim(a,i,t.flap,0,.9,0);}}
    {const arr=capyMesh.instanceMatrix.array,a=an.capybara;for(let i=0;i<capyMesh.count;i++){const c=capybaras[i];
      if(live){if(c.wait>0){c.wait-=dt;c.graze+=dt*1.5;}else{const dx=c.tx-c.x,dy=c.ty-c.y,d=Math.hypot(dx,dy);
        if(d<.02){c.wait=4+rnd()*8;for(let k=0;k<6;k++){const ang=rnd()*TAU,r=rnd()*.35,x=c.hx+Math.cos(ang)*r,y=c.hy+Math.sin(ang)*r;if(sandFree(x,y,.12)){c.tx=x;c.ty=y;break;}}}
        else{const s=Math.min(d,.06*dt);c.x+=dx/d*s;c.y+=dy/d*s;c.yaw=Math.atan2(dx,-dy);}}}
      put(arr,i,c.x,sandHeight(c.x,c.y,Math.max(0,shoreGap(c.x,c.y))),-c.y,c.yaw,1,1,1,0,0);setAnim(a,i,clock*2.4,c.wait>0?0:.35,0,c.wait>0?.35+.15*Math.sin(c.graze):0);}}
    {const arr=iguanaMesh.instanceMatrix.array,a=an.iguana,bob=live?Math.max(0,Math.sin(Math.min(1,barPhase*4)*Math.PI*2))*.35:0;
      for(let i=0;i<iguanaMesh.count;i++){const g=iguanas[i];
        if(g.balcony){const n=g.balcony.node;if(!n||n.state==='absent'){hideAt(arr,i);continue;}if(g.dirty){g.dirty=false;g.y=plateauZ(n.district)+n.h*(n.rise??1)*g.balcony.f*.45+.1;}}
        put(arr,i,g.x+Math.sin(g.yaw)*.02,g.y,g.z+Math.cos(g.yaw)*.02,g.yaw+Math.PI,1.2,1.2,1.2,g.pitch,0);setAnim(a,i,0,0,.25,-bob*(i%2?1:.6));}}
    {const arr=heronMesh.instanceMatrix.array,a=an.heron;for(let i=0;i<heronMesh.count;i++){const h=herons[i];if(live)h.strike-=dt;
      let neck=0;if(h.strike<0){neck=Math.sin(Math.min(1,-h.strike/.6)*Math.PI)*.9;if(h.strike<-.6)h.strike=6+rnd()*8;}
      put(arr,i,h.x,WATER_Y-.05,-h.y,h.yaw,1.2,1.2,1.2,0,0);setAnim(a,i,0,0,0,neck);}}
    {const arr=owlMesh.instanceMatrix.array,a=an.owl;for(let i=0;i<owlMesh.count;i++){const o=owls[i],s=nearestMover(o.x,o.z,4,false);
      const target=s>=0?Math.atan2(moverPos[s*3]-o.x,moverPos[s*3+2]-o.z)-o.yaw:(Math.floor(clock*.25+o.seed*4)%3-1)*1.1;
      o.look+=(Math.atan2(Math.sin(target),Math.cos(target))-o.look)*Math.min(1,dt*4);put(arr,i,o.x,o.y,o.z,o.yaw,1.3,1.3,1.3,0,0);setAnim(a,i,0,0,0,o.look);}}
    {const arr=robotMesh.instanceMatrix.array,r=routes[domeRoute];for(let i=0;i<robotMesh.count;i++){const q=robots[i];
      if(live){if(q.wait>0)q.wait-=dt;else{q.dist+=q.dir*q.speed*dt;if(rnd()<dt*.08)q.wait=1.5+rnd()*2.5;}}
      sampleRoute(r,q.dist,V3,q.offset);sampleRoute(r,q.dist+q.dir*.1,V4,q.offset);put(arr,i,V3.x,V3.y+.004,V3.z,Math.atan2(V4.x-V3.x,V4.z-V3.z),1,1,1,0,0);}}
    // Boats and their wakes.
    for(let k=0;k<4;k++){const bo=boats[k];if(!bo.party&&k>=boatMesh.count)continue;
      if(live)bo.theta+=bo.dir*bo.speed*dt/Math.max(.2,Math.hypot(bo.a*Math.sin(bo.theta),bo.b*Math.cos(bo.theta)));
      boatPose(bo);bo.bob=live?Math.sin(clock*1.3+k)*.012:0;bo.y=WATER_Y-(bo.party?.2:.15)+bo.bob;
      put(bo.party?partyMesh.instanceMatrix.array:boatMesh.instanceMatrix.array,bo.party?0:k,bo.x,bo.y,bo.z,bo.yaw,1,1,1,Math.sin(clock*.9+k)*.02,Math.sin(clock*1.1+k*2)*.03);
      boatState[k].set(bo.theta,bo.dir,1,0);}
    // Fish follow their school's loop; jellies drift and pulse.
    {const arr=fishMesh.instanceMatrix.array;for(let i=0;i<fishMesh.count;i++){const f=fish[i],s=SCHOOLS[f.school],th=clock*s[4]+f.off,wob=Math.sin(clock*1.3+f.wob)*.12,rr=f.r+wob*.3;
      fromLocal(s[0]+s[2]*rr*Math.cos(th),s[1]+s[3]*rr*Math.sin(th),P2);fromLocal(s[0]+s[2]*rr*Math.cos(th+.05*Math.sign(s[4])),s[1]+s[3]*rr*Math.sin(th+.05*Math.sign(s[4])),P3);
      put(arr,i,P2[0],f.y,-P2[1],Math.atan2(P3[0]-P2[0],-(P3[1]-P2[1]))+wob,.07*f.size,1,.18*f.size,0,0);}}
    {const arr=jellyMesh.instanceMatrix.array;for(let i=0;i<jellyMesh.count;i++){const j=jellies[i],ang=clock*.08+j.ph;
      put(arr,i,j.ax+Math.cos(ang)*j.r,j.y+Math.sin(clock*.5+j.ph)*.02,j.az+Math.sin(ang)*j.r,0,j.s,j.s,j.s,0,0);}}
    // Strollers walk the wet sand; they and any mover near the shore light the shallows.
    let wk=0;
    for(let i=0;i<strollers.length;i++){const st=strollers[i];if(live){st.t+=st.dir*st.speed*dt/shoreSpeed(st.t);if(st.t>st.t1){st.t=st.t1;st.dir=-1;}else if(st.t<st.t0){st.t=st.t0;st.dir=1;}}
      if(wk<12&&i<strollCap())walkGlow[wk++].set(st.x,-st.z,1,0);}
    for(let s=0;s<MOVERS&&wk<12;s++)if(moverLive(s))walkGlow[wk++].set(moverPos[s*3],-moverPos[s*3+2],1,0);
    for(;wk<12;wk++)walkGlow[wk].z=0;
    // The bonfire flickers (still with reduced motion).
    fireLight.z=live?.85+.15*Math.sin(clock*11.3)*Math.sin(clock*7.1+1.3):.9;
    for(let i=0;i<meshList.length;i++)meshList[i].instanceMatrix.needsUpdate=true;
    for(let i=0;i<animList.length;i++)animList[i].needsUpdate=true;
  }

  // ------------------------------------------------------------------ the S4 camera and QA handles
  // S4 (C13.3): standing on the Reef shore sand at eye height, beside the pier on the side away from the bar,
  // looking over the lake at the island stage (its crowd and LED wall face the pier).
  function cameraS4(){let best=null;
    for(let k=0;k<60&&!best;k++){const t=tPier-barSide*(.3+k*.02);shorePoint(t,.6,P2);if(sandFree(P2[0],P2[1],.4))best=[P2[0],P2[1]];}
    if(!best){shorePoint(tPier-barSide*.6,.6,P2);best=[P2[0],P2[1]];}
    camera.position.set(best[0],sandHeight(best[0],best[1],.6)+.45,-best[1]);controls.target.set(ISLE.x,ISLE.z+.15,-ISLE.y);controls.update();
    return {position:camera.position.toArray(),target:controls.target.toArray()};}
  function census(){const out={tier:currentTier};
    for(const k in meshes){const m=meshes[k],a=m.instanceMatrix.array;let visible=0;for(let i=0;i<m.count;i++){const o=i*16;if(a[o+15]===1&&Math.hypot(a[o],a[o+1],a[o+2])>1e-6)visible++;}
      out[k]={spec:COUNTS[k],allocated:allocated[k],rendered:m.count,visible};}
    out.firefly={spec:COUNTS.firefly,allocated:flyAnchors.length/3,rendered:flyGeo.drawRange.count,visible:Math.min(flyGeo.drawRange.count,flyAnchors.length/3)};
    return out;}
  // Rendered instance positions of one population (three.js coordinates), for the gates.
  function positions(kind){const m=meshes[kind],a=m.instanceMatrix.array,out=[];for(let i=0;i<m.count;i++){const o=i*16;if(a[o+15]===1&&Math.hypot(a[o],a[o+1],a[o+2])>1e-6)out.push([a[o+12],a[o+13],a[o+14]]);}return out;}
  return {update,surfaceAt,isBlocked,isWater,shoreGap,sandHeight,mover,cameraS4,census,positions,applyTier,counts:COUNTS,people:LAKE_PEOPLE,tierCount,extras,reserve,diagnostics,
    lake:{cx:LAKE.cx,cy:LAKE.cy,rx:AX,ry:BY,angle:LAKE.angle,y:WATER_Y,pier:PIER,island:ISLE},railOpening:SHORE.rail,
    animals:{dogs,cats,pigeons,flocks,bats,capybaras,iguanas,herons,owls,robots,boats,fish,jellies,strollers},meshes,group,water,shore:shoreMesh,
    trees:{palms:palmMesh,tropical:broadMesh,balcony:balconyMesh,data:TREES},fireflies,flames,
    plateaus:Object.fromEntries(Object.entries(DATA.plateaus).map(([d,p])=>[d,{cx:p.cx,cz:-p.cy,z:p.z}])),
    materials:{water:waterMat,shore:shoreMat,critter:critterMat,plant:plantMat,fish:fishMat,jelly:jellyMat}};
})();
