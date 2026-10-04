// Geometry-derived bend sections, and measurements at shared distance boundaries.
const InputScopeLab=(()=>{
 const lerp=(rows,d,col=0)=>{let lo=0,hi=rows.length-1;while(lo<hi){const m=(lo+hi)>>1;if(rows[m][col]<d)lo=m+1;else hi=m}if(!lo)return rows[0];const a=rows[lo-1],b=rows[lo],f=Math.max(0,Math.min(1,(d-a[col])/Math.max(1e-9,b[col]-a[col])));return a.map((v,k)=>v+(b[k]-v)*f)};
 const wrap=f=>((f%1)+1)%1;
 function validateCalibration(v,L){
  if(!v||v.version!==1||!Number.isFinite(v.offset_m)||Math.abs(v.offset_m)>L||![1,-1].includes(v.direction)||!Array.isArray(v.anchors)||v.anchors.length>30)throw Error('校准参数无效');
  const knots=[[0,0]],anchors=v.anchors.slice().sort((a,b)=>a.distance_m-b.distance_m),offset=wrap(v.offset_m/L);
  for(const a of anchors){if(!Number.isFinite(a.distance_m)||!Number.isFinite(a.shape_fraction)||a.distance_m<=0||a.distance_m>=L||a.shape_fraction<0||a.shape_fraction>=1)throw Error('锚点范围无效');const u=wrap((a.shape_fraction-offset)*v.direction);if(a.distance_m<=knots.at(-1)[0]||u<=knots.at(-1)[1])throw Error('锚点顺序冲突，请先设置起终点和方向');knots.push([a.distance_m,u])}
  return {...v,anchors,knots:[...knots,[L,1]]};
 }
 function fraction(d,L,v){v=validateCalibration(v,L);return wrap(v.offset_m/L+v.direction*lerp(v.knots,Math.max(0,Math.min(L,d)))[1])}
 function distance(f,L,v){v=validateCalibration(v,L);const u=wrap((f-v.offset_m/L)*v.direction);return lerp(v.knots,u,1)[0]}
 function baseline(entries,L){
  const complete=entries.filter(e=>e.points?.length>=3&&e.points[0][1]<L*.03&&e.points.at(-1)[1]>L*.97&&e.points.every((p,i)=>!i||p[1]>=e.points[i-1][1]));
  if(complete.length<2||new Set(complete.map(e=>e.coordinateSource||'recorded_world_xz')).size!==1)return null;
  const points=[],median=a=>{a.sort((x,y)=>x-y);return (a[(a.length-1)>>1]+a[a.length>>1])/2};
  for(let i=0;i<=600;i++){const d=L*i/600,values=complete.map(e=>InputScopeTrack.interpolate(e.points,d/L*e.length,1)).filter(Boolean);if(values.length<2)return null;points.push([i/600,d,median(values.map(p=>p[2])),median(values.map(p=>p[3]))])}
  return {points,length:L,duration:1,count:complete.length};
 }
 function validateCorners(items,L){
  if(!Array.isArray(items)||items.length>150)throw Error('弯段格式无效');let end=-1;
  return items.map((c,i)=>{if(!c||![c.start,c.apex,c.end].every(Number.isFinite)||c.start<0||c.end>L||c.start<end||!(c.start<c.apex&&c.apex<c.end)||typeof c.name!=='string'||!c.name.trim()||c.name.length>60)throw Error('弯段必须按距离排序且不重叠，满足 起点 < 弯心 < 终点');end=c.end;return {...c,name:c.name.trim(),source:'manual'}});
 }
 function corners(lap,diagram,events=[]){
  const L=lap.lap.track_length_m,trajectory=lap.trajectory?.points,actual=trajectory?.length>3,step=Math.max(4,L/2500),p=[];
  if(actual||diagram)for(let d=0;d<=L;d+=step){const v=actual?InputScopeTrack.interpolate(trajectory,d,1):InputScopeTrack.shapeAt(diagram,d/L);if(v)p.push([d,...(actual?v.slice(2):v)])}
  const bends=[];let active=null;
  for(let i=4;i<p.length-4;i++){const a=p[i-4],b=p[i],c=p[i+4];if(c[0]-a[0]>step*9)continue;const h1=Math.atan2(b[2]-a[2],b[1]-a[1]),h2=Math.atan2(c[2]-b[2],c[1]-b[1]),angle=Math.abs(Math.atan2(Math.sin(h2-h1),Math.cos(h2-h1)));
   if(angle>.11){if(!active)active={start:b[0],end:b[0],apex:b[0],peak:angle};active.end=b[0];if(angle>active.peak){active.peak=angle;active.apex=b[0]}}
   else if(active){if(active.end-active.start>=step*2)bends.push(active);active=null}
  }
  if(active)bends.push(active);
  const merged=[];for(const b of bends){const a=merged.at(-1);if(a&&b.start-a.end<30){a.end=b.end;if(b.peak>a.peak){a.apex=b.apex;a.peak=b.peak}}else merged.push({...b})}
  if(!merged.length){for(const e of events)merged.push({start:e.start,end:e.release,apex:(e.start+e.release)/2});}
  return merged.map((b,i)=>({name:(actual||diagram?'自动弯段 A':'制动区 B')+(i+1),apex:b.apex,
   start:Math.max(0,Math.min(b.start-80,i?(merged[i-1].apex+b.apex)/2:0)),
   end:Math.min(L,i<merged.length-1?(b.apex+merged[i+1].apex)/2:L),source:actual?'trajectory':diagram?'diagram_estimate':'braking_fallback'})).map((b,i,all)=>({...b,start:i?all[i-1].end:b.start}));
 }
 function measure(lap,corner,at,offset=2){
  const step=Math.max(1,(corner.end-corner.start)/1500),rows=[];
  for(let d=corner.start;d<corner.end;d+=step)rows.push(at(lap,d));rows.push(at(lap,corner.end));
  const brake=rows.find(r=>r[0]<=corner.apex&&r[offset+1]>=.05),released=brake?rows.find(r=>r[0]>brake[0]&&r[offset+1]<.05):null;
  const after=rows.filter(r=>r[0]>=corner.apex),recovery=after.find((r,i)=>r[offset]>=.9&&after.slice(i).some(q=>q[0]>=r[0]+12)&&after.filter(q=>q[0]>=r[0]&&q[0]<=r[0]+12).every(q=>q[offset]>=.9));
  return {brake:brake?.[0]??null,release:released?.[0]??null,minimum:Math.min(...rows.map(r=>r[6])),entry:rows[0][6],exit:rows.at(-1)[6],full:recovery?.[0]??null,time:rows.at(-1)[1]-rows[0][1]};
 }
 return {lerp,wrap,validateCalibration,fraction,distance,baseline,corners,validateCorners,measure};
})();
