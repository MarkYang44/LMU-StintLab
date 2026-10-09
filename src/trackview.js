// Offline map renderer. Recorded trajectories work without a base-map catalog.
const trackCatalog=/*TRACK_CATALOG*/null;
const InputScopeTrack=(()=>{
 function interpolate(points,target,column=0,maxGap=1.5){
  if(!points?.length||target<points[0][column]-.05||target>points.at(-1)[column]+.05)return null;
  let lo=0,hi=points.length-1;while(lo<hi){const m=(lo+hi)>>1;if(points[m][column]<target)lo=m+1;else hi=m}
  const b=points[lo];if(lo===0||Math.abs(b[column]-target)<1e-7)return b.slice();
  const a=points[lo-1];if(b[0]-a[0]>maxGap||Math.hypot(b[2]-a[2],b[3]-a[3])>Math.max(100,(b[0]-a[0])*150+10))return null;
  const f=Math.max(0,Math.min(1,(target-a[column])/Math.max(1e-9,b[column]-a[column])));
  return a.map((v,k)=>v+(b[k]-v)*f);
 }
 const nameKey=track=>String(track).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\b(?:wec|elms|20\d{2})\b/g,'').replace(/[^a-z0-9]/g,'');
 function official(track,length,allowDefault=false){const key=nameKey(track),candidates=(trackCatalog||[]).filter(v=>v.aliases.some(n=>nameKey(n)===key)),matches=candidates.filter(v=>Math.abs(v.length_m-length)/v.length_m<.06).sort((a,b)=>Math.abs(a.length_m-length)-Math.abs(b.length_m-length));return matches[0]||(allowDefault?candidates.find(v=>v.layout==='Full')||candidates[0]:null)||null}
 function shapeAt(shape,fraction){
  const points=shape.points,f=Math.max(0,Math.min(1,fraction));
  let lo=0,hi=points.length-1;while(lo<hi){const m=(lo+hi)>>1;if(points[m][0]<f)lo=m+1;else hi=m}
  if(!lo)return points[0].slice(1);const a=points[lo-1],b=points[lo],u=(f-a[0])/Math.max(1e-9,b[0]-a[0]);
  return [a[1]+u*(b[1]-a[1]),a[2]+u*(b[2]-a[2])];
 }
 // World X/Z is left-handed (+Y up); Mercator is east/north. Canvas is Y-down.
 // Reference SVG/PDF outlines already use screen coordinates and must not flip.
 function projection(bounds,w,h,options={}){
  const {minX,maxX,minY,maxY}=bounds,{invertY=false,rotation=0,zoom=1,panX=0,panY=0}=options;
  const sign=invertY?-1:1,angle=rotation*Math.PI/180,cos=Math.cos(angle),sin=Math.sin(angle);
  const dx=maxX-minX,dy=maxY-minY,extentX=Math.abs(cos)*dx+Math.abs(sin)*dy,extentY=Math.abs(sin)*dx+Math.abs(cos)*dy;
  const scale=Math.min((w-64)/Math.max(1,extentX),(h-70)/Math.max(1,extentY))*zoom;
  return (x,y)=>{x-=(minX+maxX)/2;y=(y-(minY+maxY)/2)*sign;return [(x*cos-y*sin)*scale+w/2+panX,(x*sin+y*cos)*scale+h/2+panY]};
 }
 class View{
  constructor(canvas,mode,source){this.canvas=canvas;this.ctx=canvas.getContext('2d');this.back=document.createElement('canvas');this.bg=this.back.getContext('2d');this.mode=mode;this.source=source;this.entries=[];this.key='';this.lastStates=[];this.zoom=1;this.panX=0;this.panY=0;this.rotation=0;
   const bar=document.createElement('div');bar.className='map-navigation';Object.assign(bar.style,{display:'flex',gap:'7px',alignItems:'center',flexWrap:'wrap',margin:'8px 0'});
   const button=(text,title,action)=>{const b=document.createElement('button');b.type='button';b.textContent=text;b.title=title;b.setAttribute('aria-label',title);b.onclick=action;bar.append(b);return b};
   button('−','缩小赛道地图',()=>this.zoomAt(1/1.4));button('＋','放大赛道地图',()=>this.zoomAt(1.4));this.zoomLabel=document.createElement('span');this.zoomLabel.style.cssText='font-size:12px;color:#91a4bf;min-width:38px';bar.append(this.zoomLabel);button('↶','逆时针旋转赛道图 90°',()=>this.rotate(-90));button('↷','顺时针旋转赛道图 90°',()=>this.rotate(90));button('还原','还原完整赛道视图',()=>this.resetView());const hint=document.createElement('small');hint.textContent='滚轮缩放 · 拖动查看';bar.append(hint);canvas.before(bar);canvas.style.cursor='grab';
   canvas.addEventListener('wheel',e=>{e.preventDefault();const r=canvas.getBoundingClientRect();this.zoomAt(Math.exp(-e.deltaY*.0015),e.clientX-r.left,e.clientY-r.top)},{passive:false});
   canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;this.drag={id:e.pointerId,x:e.clientX,y:e.clientY,panX:this.panX,panY:this.panY};canvas.setPointerCapture(e.pointerId);canvas.style.cursor='grabbing'});
   canvas.addEventListener('pointermove',e=>{if(!this.drag||e.pointerId!==this.drag.id)return;this.panX=this.drag.panX+e.clientX-this.drag.x;this.panY=this.drag.panY+e.clientY-this.drag.y;this.draw(this.lastStates)});
   canvas.addEventListener('pointerup',e=>{if(this.drag&&Math.hypot(e.clientX-this.drag.x,e.clientY-this.drag.y)<5){const r=canvas.getBoundingClientRect();this.pick(e.clientX-r.left,e.clientY-r.top)}this.drag=null;canvas.style.cursor='grab'});
   const stop=()=>{this.drag=null;canvas.style.cursor='grab'};canvas.addEventListener('pointercancel',stop);canvas.addEventListener('lostpointercapture',stop);canvas.addEventListener('dblclick',()=>this.resetView());
   const details=document.createElement('details');details.className='map-calibration';details.style.cssText='font-size:12px;line-height:1.8;margin:8px 0';const summary=document.createElement('summary');summary.textContent='地图校准 / 走线放大 / 导入导出';details.append(summary);
   const tools=document.createElement('div');tools.style.cssText='display:flex;gap:7px;flex-wrap:wrap;margin-top:8px';details.append(tools);bar.after(details);this.calibrationUI=details;
   const make=(label,action)=>{const b=document.createElement('button');b.textContent=label;b.onclick=action;tools.append(b);return b};
   this.calibrationHint=document.createElement('div');details.append(this.calibrationHint);
   this.offsetInput=document.createElement('input');this.offsetInput.type='number';this.offsetInput.value=0;this.offsetInput.style.width='100px';this.offsetInput.title='起终点在轮廓周长上的偏移（米）';this.offsetInput.setAttribute('aria-label','地图起终点偏移米');const offsetLabel=document.createElement('label');offsetLabel.append(document.createTextNode('S/F m '),this.offsetInput);tools.append(offsetLabel);
   this.reverseInput=document.createElement('input');this.reverseInput.type='checkbox';const label=document.createElement('label');label.append(this.reverseInput,document.createTextNode('反向'));tools.append(label);
   make('应用偏移',()=>this.applyCalibration({version:1,offset_m:Number(this.offsetInput.value),direction:this.reverseInput.checked?-1:1,anchors:[]}));
   make('点击设 S/F',()=>{this.pickMode='start';this.calibrationHint.textContent='请点击轮廓上的起终点'});
   this.anchorInput=document.createElement('input');this.anchorInput.type='number';this.anchorInput.value=1000;this.anchorInput.style.width='95px';this.anchorInput.title='该点在游戏中的圈内距离（米）';this.anchorInput.setAttribute('aria-label','地图锚点圈内距离米');const anchorLabel=document.createElement('label');anchorLabel.append(document.createTextNode('距离 m '),this.anchorInput);tools.append(anchorLabel);
   make('点击设锚点',()=>{this.pickMode='anchor';this.calibrationHint.textContent='请点击上述圈内距离对应的轮廓位置'});
   this.lineScale=document.createElement('select');this.lineScale.setAttribute('aria-label','走线横向放大倍率');for(const n of [1,2,5,10]){const o=document.createElement('option');o.value=n;o.textContent='走线偏差 ×'+n;this.lineScale.append(o)}tools.append(this.lineScale);this.lineScale.onchange=()=>{this.key='';this.draw(this.lastStates)};
   make('清除校准',()=>this.applyCalibration({version:1,offset_m:0,direction:1,anchors:[]}));
   make('导出校准',()=>{const a=document.createElement('a'),u=URL.createObjectURL(new Blob([JSON.stringify(this.exportState(),null,2)],{type:'application/json'}));a.href=u;a.download='InputScope_map_calibration.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),2000)});
   const file=document.createElement('input');file.type='file';file.accept='.json';file.style.display='none';tools.append(file);make('导入校准',()=>file.click());file.onchange=async()=>{try{const v=JSON.parse(await file.files[0].text());this.restoreState(v)}catch(e){this.calibrationHint.textContent='导入失败：'+e.message}file.value=''};
  }
  storageKey(){return 'inputscope.map.v1.'+nameKey(this.track)+'.'+Math.round(this.length)+'.'+(this.diagram?.layout||'world')}
  exportState(){return {format:'inputscope.map-calibration',track:this.track,length_m:this.length,layout:this.diagram?.layout||'world',calibration:this.calibration,line_scale:Number(this.lineScale.value)}}
  restoreState(v){if(v.format!=='inputscope.map-calibration'||nameKey(v.track)!==nameKey(this.track)||Math.abs(v.length_m-this.length)>1||(v.layout||'world')!==(this.diagram?.layout||'world'))throw Error('校准与当前赛道布局不匹配');this.lineScale.value=[1,2,5,10].includes(v.line_scale)?v.line_scale:1;this.applyCalibration(v.calibration)}
  applyCalibration(v){try{this.calibration=InputScopeLab.validateCalibration(v,this.length);this.offsetInput.value=v.offset_m;this.reverseInput.checked=v.direction===-1;this.calibrationHint.textContent=this.route?'实测坐标保留原位；校准仅用于无坐标轮廓估算。':'估算位置已校准 · '+v.anchors.length+' 个锚点';try{localStorage.setItem(this.storageKey(),JSON.stringify(this.exportState()))}catch{}this.key='';this.draw(this.lastStates)}catch(e){this.calibrationHint.textContent=e.message}}
  pick(x,y){
   if(!this.project)return;let nearest=null,best=Infinity;const points=this.route?this.route.points:this.diagram?.points||[];
   for(const p of points){const xy=this.route?this.linePosition(p.slice(2),p[1]):p.slice(1),q=this.project(...xy),dd=Math.hypot(x-q[0],y-q[1]);const temporal=this.route?Math.abs(p[0]-(this.lastStates[0]?.t||0))*.00001:0;if(dd+temporal<best){best=dd+temporal;nearest=p}}
   if(!nearest||best>30)return;
   if(this.pickMode){if(this.route){this.calibrationHint.textContent='实测坐标不需要轮廓校准；请使用无坐标日志校准赛道图。';this.pickMode=null;return}const v={...this.calibration,anchors:this.calibration.anchors.slice()};if(this.pickMode==='start'){v.offset_m=nearest[0]*this.length;v.anchors=[]}else v.anchors.push({distance_m:Number(this.anchorInput.value),shape_fraction:nearest[0]});this.pickMode=null;this.applyCalibration(v);return}
   const d=this.route?nearest[1]/this.route.length*this.length:InputScopeLab.distance(nearest[0],this.length,this.calibration);this.onSeekDistance?.(d,nearest[0]);
  }
  zoomAt(factor,x=this.w/2,y=this.h/2){const next=Math.max(.5,Math.min(20,this.zoom*factor)),ratio=next/this.zoom;this.panX=x-this.w/2-(x-this.w/2-this.panX)*ratio;this.panY=y-this.h/2-(y-this.h/2-this.panY)*ratio;this.zoom=next;this.draw(this.lastStates)}
  rotate(degrees){this.rotation=(this.rotation+degrees)%360;this.panX=0;this.panY=0;this.draw(this.lastStates)}
  resetView(){this.zoom=1;this.panX=0;this.panY=0;this.rotation=0;this.draw(this.lastStates)}
  setEntries(entries,track,length){
   const frame=entries.find(e=>e.points?.length)?.coordinateSource||'recorded_world_xz';
   this.entries=entries.map(e=>({...e,points:(e.coordinateSource||'recorded_world_xz')===frame?e.points:[],frameMismatch:(e.coordinateSource||'recorded_world_xz')!==frame}));this.track=track;this.length=length;this.zoom=1;this.panX=0;this.panY=0;this.rotation=0;this.lastStates=[];
   this.frame=frame;entries=this.entries;
   this.route=entries.find(e=>e.points?.length>=3)||null;
   this.diagram=this.route?null:official(track,length);
   this.baseline=InputScopeLab.baseline(entries,length);
   this.calibration={version:1,offset_m:0,direction:1,anchors:[]};try{const saved=JSON.parse(localStorage.getItem(this.storageKey()));if(saved)this.restoreState(saved)}catch{}
   this.offsetInput.value=this.calibration.offset_m;this.reverseInput.checked=this.calibration.direction===-1;
   this.mode.textContent=this.route?'LMU 实测轨迹':this.diagram?(this.diagram.source_kind==='community'?'社区赛道图 · 位置估算':'官方赛道图 · 位置估算'):'圈内进度 · 无坐标';
   this.source.replaceChildren();
   if(this.route)this.source.textContent=(frame.startsWith('gps_')?'GPS 经纬度投影坐标（带地图投影误差）。':'形状与坐标：LMU mPos 的 X/Z 俯视轨迹（已校正镜像）。')+'缺口不跨越插值；无坐标圈按轨迹距离估算。'+(this.baseline?' 灰色为 '+this.baseline.count+' 圈距离对齐的中位走线；可放大横向走线偏差。':' 点击走线定位曲线。')+(entries.some(e=>e.frameMismatch)?' 不同坐标系的圈仅显示距离估算位置。':'');
   else if(this.diagram){const a=document.createElement('a');a.href=this.diagram.source_pdf_url||this.diagram.source_url;a.textContent=this.diagram.source_title;a.target='_blank';a.rel='noreferrer';this.source.append(a,document.createTextNode(' · '+(this.diagram.source_kind==='community'?'社区矢量轮廓':'官方矢量轮廓')+'；位置按圈内距离比例估算，不代表精确走线。'))}
   else this.source.textContent='该记录没有世界坐标，也没有匹配布局的可信地图；仅展示圈内进度。';
   this.key='';this.background();
  }
  linePosition(xy,d){
   if(!this.baseline||Number(this.lineScale.value)<=1)return xy;
   const center=interpolate(this.baseline.points,d,1,2),a=interpolate(this.baseline.points,Math.max(0,d-8),1,2),b=interpolate(this.baseline.points,Math.min(this.length,d+8),1,2);
   if(!center||!a||!b)return xy;const dx=b[2]-a[2],dy=b[3]-a[3],n=Math.hypot(dx,dy)||1,side=(xy[0]-center[2])*(-dy/n)+(xy[1]-center[3])*(dx/n),extra=side*(Number(this.lineScale.value)-1);return [xy[0]-dy/n*extra,xy[1]+dx/n*extra];
  }
  background(){
   const w=Math.max(220,this.canvas.clientWidth),h=Math.max(240,this.canvas.clientHeight),dpr=devicePixelRatio||1,key=[globalThis.StintrixTheme?.mode||'dark',w,h,dpr,this.zoom,this.panX,this.panY,this.lineScale.value,this.rotation].join('|');
   if(key===this.key)return;this.key=key;this.w=w;this.h=h;this.dpr=dpr;this.zoomLabel.textContent=Math.round(this.zoom*100)+'%';
   this.canvas.width=this.back.width=Math.round(w*dpr);this.canvas.height=this.back.height=Math.round(h*dpr);
   const c=this.bg;c.setTransform(dpr,0,0,dpr,0,0);c.fillStyle=(globalThis.StintrixTheme?.color('CARD')||'#101a28');c.fillRect(0,0,w,h);c.font='12px system-ui';
   let shape=[];
   if(this.route){for(const e of this.entries)for(const p of e.points||[])shape.push([p[2],p[3]])}
   else if(this.diagram)shape=this.diagram.points.map(p=>p.slice(1));
   if(!shape.length){c.fillStyle=(globalThis.StintrixTheme?.color('MUTED')||'#91a5c0');c.fillText(this.entries.length?'旧日志 / 圈内距离位置':'暂无圈数据',16,28);return}
   let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
   for(const p of shape){minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1])}
   this.project=projection({minX,maxX,minY,maxY},w,h,{invertY:Boolean(this.route)&&(this.frame==='recorded_world_xz'||this.frame?.startsWith('gps_')),rotation:this.rotation,zoom:this.zoom,panX:this.panX,panY:this.panY});
   const stroke=(points,color,width,withTime)=>{c.strokeStyle=color;c.lineWidth=width;c.lineJoin='round';c.lineCap='round';c.beginPath();let previous=null;
    for(const p of points){const xy=withTime&&points!==this.baseline?.points?this.linePosition(p.slice(2),p[1]):p.slice(withTime?2:1),position=this.project(...xy);
     const gap=previous&&(p[0]-previous[0]>1.5||Math.hypot(p[2]-previous[2],p[3]-previous[3])>Math.max(100,(p[0]-previous[0])*150+10));
     if(!previous||withTime&&gap)c.moveTo(...position);else c.lineTo(...position);previous=p}c.stroke()};
   if(this.diagram){stroke(this.diagram.points,(globalThis.StintrixTheme?.color('EDGE')||'#334962'),9,false);stroke(this.diagram.points,(globalThis.StintrixTheme?.color('MUTED')||'#8ca5c4'),2,false)}
   else{stroke((this.baseline||this.route).points,(globalThis.StintrixTheme?.color('EDGE')||'#34485e'),9,true);for(const e of this.entries)if(e.points?.length)stroke(e.points,e.color+'cc',1.7,true)}
   if(this.selectedCorner){const part=this.selectedCorner,xy=this.route?interpolate(this.route.points,part.apex,1)?.slice(2):this.diagram?shapeAt(this.diagram,InputScopeLab.fraction(part.apex,this.length,this.calibration)):null;if(xy){const p=this.project(...xy);c.strokeStyle='#f4d67d';c.lineWidth=2;c.beginPath();c.arc(...p,13,0,Math.PI*2);c.stroke();c.fillStyle='#f4d67d';c.fillText(part.name,p[0]+17,p[1]-5)}}
   const start=this.route?this.route.points[0].slice(2):shapeAt(this.diagram,InputScopeLab.fraction(0,this.length,this.calibration)),p=this.project(...start);
   c.fillStyle=(globalThis.StintrixTheme?.color('FG')||'#eef4ff');c.fillRect(p[0]-4,p[1]-4,8,8);if(p[0]>=0&&p[0]<=w&&p[1]>=0&&p[1]<=h){c.fillStyle=(globalThis.StintrixTheme?.color('MUTED')||'#a7bad2');c.fillText(this.route?.startLabel||'S/F',Math.min(w-55,p[0]+8),Math.max(16,p[1]-8))}
  }
  draw(states){
   this.lastStates=states;this.background();const c=this.ctx,w=this.w,h=this.h;c.setTransform(1,0,0,1,0,0);c.drawImage(this.back,0,0);c.setTransform(this.dpr,0,0,this.dpr,0,0);c.font='12px system-ui';
   const results=[];
   states.forEach((state,i)=>{
    const entry=this.entries.find(e=>e.id===state.id);if(!entry)return;
    const progress=Math.max(0,Math.min(1,state.d/entry.length)),inside=state.d>=0&&state.d<=entry.length+.1;let xy=null,kind='unknown';
    if(entry.points?.length){const p=interpolate(entry.points,Math.min(state.t,entry.duration));if(p){xy=this.linePosition(p.slice(2),p[1]);kind='recorded'}}
    else if(this.route&&inside){const p=interpolate(this.route.points,progress*this.route.length,1);if(p){xy=p.slice(2);kind='distance_estimate'}}
    else if(this.diagram&&inside){xy=shapeAt(this.diagram,InputScopeLab.fraction(state.d,this.length,this.calibration));kind='distance_estimate'}
    if(!this.route&&!this.diagram){const y=65+i*Math.min(48,(h-100)/Math.max(1,states.length));c.strokeStyle='#344962';c.lineWidth=5;c.beginPath();c.moveTo(18,y);c.lineTo(w-18,y);c.stroke();if(inside){xy=[18+progress*(w-36),y];kind='progress'}c.fillStyle=entry.color;c.fillText(entry.title,18,y-14)}
    else if(xy)xy=this.project(...xy);
    if(xy&&xy[0]>=-10&&xy[0]<=w+10&&xy[1]>=-10&&xy[1]<=h+10){c.strokeStyle=entry.color+'55';c.lineWidth=3;c.beginPath();c.arc(xy[0],xy[1],9+i*.8,0,Math.PI*2);c.stroke();c.fillStyle=entry.color;c.strokeStyle='#f4f8ff';c.lineWidth=1.5;c.beginPath();c.arc(xy[0],xy[1],4.5,0,Math.PI*2);c.fill();c.stroke();c.fillStyle=entry.color;c.fillText(String(i+1),Math.min(w-14,xy[0]+10),Math.max(15,xy[1]-10-i*12))}
    results.push({...state,kind:kind,xy:xy});
   });
   return results;
  }
 }
 return {View,interpolate,official,shapeAt,projection};
})();
