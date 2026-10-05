/* Shared offline tyre/energy view. All values originate in recorded telemetry. */
const InputScopeVehicle=(()=>{
 const wheels=['fl','fr','rl','rr'],names=['左前 FL','右前 FR','左后 RL','右后 RR'],wheelColors=['#69b8ff','#ffb86b','#c99aff','#67e3bc'];
 const metrics=[['fuel_l','燃油','L',1],['pressure_kpa','胎压','kPa',1],['inner_c','胎面内侧','°C',1],['middle_c','胎面中部','°C',1],['outer_c','胎面外侧','°C',1],['carcass_c','胎体温度','°C',1],['wear_fraction','胎况字段','%',100],['battery_soc_pct','电池电量','%',1],['virtual_energy_pct','虚拟能量','%',1],['regen_kw','游戏回收功率','kW',1],['electric_power_kw','电机机械功率','kW',1]];
 metrics.push(['rain_severity','雨量强度','%',100],['wetness','平均赛道湿度','%',100],['track_temp_c','赛道温度','°C',1],['ambient_temp_c','环境温度','°C',1]);
 const direct=new Set(['fuel_l','battery_soc_pct','virtual_energy_pct','regen_kw','electric_power_kw','rain_severity','wetness','track_temp_c','ambient_temp_c']);
 const fmt=(v,d=1)=>Number.isFinite(v)?v.toFixed(d):'—';
 function validate(v){
  if(v==null)return null;
  if(v.version!==1||!Array.isArray(v.columns)||v.columns.length>128||new Set(v.columns).size!==v.columns.length||!v.columns.every(k=>typeof k==='string'&&/^[a-z_]+$/.test(k))||!Array.isArray(v.data)||v.data.length>500000)throw Error('轮胎／能量遥测格式无效');
  let t=-Infinity;for(const r of v.data){if(!Array.isArray(r)||r.length!==v.columns.length+1||!Number.isFinite(r[0])||r[0]<=t||r.slice(1).some(x=>x!==null&&(!Number.isFinite(x)||Math.abs(x)>1e8)))throw Error('附加遥测时间或数值无效');t=r[0]}
  return v;
 }
 function at(bundle,t){
  if(!bundle?.data?.length)return {};const rows=bundle.data;let lo=0,hi=rows.length-1;
  while(lo<hi){const m=(lo+hi)>>1;if(rows[m][0]<t)lo=m+1;else hi=m}
  const b=rows[lo],a=rows[Math.max(0,lo-1)];if(t<rows[0][0]-.15||t>rows.at(-1)[0]+.15||b[0]-a[0]>1.5)return {};
  const f=a===b?0:Math.max(0,Math.min(1,(t-a[0])/(b[0]-a[0]))),values={};
  bundle.columns.forEach((k,i)=>{const x=a[i+1],y=b[i+1];const held=/_(flat|detached|index)$/.test(k)||['lap','in_pits','lap_invalidated','pit_state','speed_limiter','pit_stops','motor_state','race_session','completed_laps','max_laps','lap_start_s'].includes(k);values[k]=x===null||y===null?null:held?(f>=1?y:x):x+(y-x)*f});return values;
 }
 function fuelEstimate(entry,t,v){
  const changes=entry.bundle?.strategy_history||[],conf=[...changes].reverse().find(c=>c.time_s<=t)?.strategy||entry.bundle?.strategy||{},history=(entry.stint_laps||[]).filter(r=>r.end_time_s<=t&&r.vehicle_summary?.fuel_l_used?.value>0).slice(-(conf.history_laps||5));
  const sorted=history.map(r=>r.vehicle_summary.fuel_l_used.value).sort((a,b)=>a-b),middle=a=>a.length?(a[(a.length-1)>>1]+a[a.length>>1])/2:null;
  const rate=conf.rate_mode==='median'?middle(sorted):sorted.at(-1),dur=middle(history.map(r=>r.time_s).sort((a,b)=>a-b));
  let remaining=null;const progress=Math.max(0,Math.min(1,(entry.distance?.(t)||0)/(entry.length||1)));
  if(conf.target_mode==='laps'&&v.completed_laps!=null)remaining=Math.max(0,(conf.target_value||0)-v.completed_laps-progress);
  else{
   const choices=[];if(conf.target_mode!=='time'&&v.race_session&&v.max_laps&&v.completed_laps!=null)choices.push(Math.max(0,v.max_laps-v.completed_laps-progress));
   const seconds=conf.target_mode==='time'?Math.max(0,(conf.target_value||0)*60-(t-(conf.started_at_s||0))):v.race_session?v.remaining_s:null;
   if(seconds!=null&&dur)choices.push(Math.max(0,Math.ceil(progress+seconds/dur)-progress)+(conf.extra_finish_laps??1));
   if(choices.length)remaining=Math.min(...choices);
  }
  const required=remaining!=null&&rate!=null?remaining*rate+(remaining>0?(conf.reserve_l??2):0):null;
  return {count:history.length,rate,range:v.fuel_l!=null&&rate?v.fuel_l/rate:null,remaining,required,margin:v.fuel_l!=null&&required!=null?v.fuel_l-required:null};
 }
 class View{
  constructor(mount,onSeek){
   mount.replaceChildren();
   this.mount=mount;this.onSeek=onSeek;this.entries=[];this.key='';this.time=0;this.range=[0,1];
   const style=document.createElement('style');style.textContent='.vehicle-head,.vehicle-tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.vehicle-head{justify-content:space-between}.vehicle-snapshot{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:14px 0}.vehicle-box{padding:13px;background:var(--sl-card,#101a28);border:1px solid var(--sl-edge,#30435c);border-radius:12px;min-width:0}.vehicle-box h3{margin:0 0 9px;font-size:14px}.vehicle-tyres{display:grid;grid-template-columns:1fr 1fr;gap:8px}.vehicle-wheel{border:1px solid #2c3d53;border-radius:8px;padding:9px;font-size:12px;line-height:1.8}.vehicle-value{font-size:20px;font-weight:650;font-variant-numeric:tabular-nums}.vehicle-warning{color:#ffb99a}.vehicle-table{overflow:auto}.vehicle-table table{font-size:12px;min-width:700px}.vehicle-table td,.vehicle-table th{padding:9px;border-bottom:1px solid var(--sl-edge,#2a3b52);text-align:left}.vehicle-chart{height:235px!important}.vehicle-note{font-size:12px;line-height:1.7;color:var(--sl-muted,#91a4bf)}.vehicle-tools select{max-width:100%}.vehicle-readout{line-height:1.8;font-variant-numeric:tabular-nums;font-size:12px;min-height:23px}';mount.append(style);
   const head=document.createElement('div');head.className='vehicle-head';const h=document.createElement('h2');h.textContent='四轮轮胎 / 燃油与能量';head.append(h);mount.append(head);
   this.tools=document.createElement('div');this.tools.className='vehicle-tools';mount.append(this.tools);this.metric=document.createElement('select');this.metric.setAttribute('aria-label','轮胎与能量通道');this.metric.id='vehicle-channel';this.wheel=document.createElement('select');this.wheel.setAttribute('aria-label','遥测车轮');this.wheel.id='vehicle-wheel';
   for(const [k,label] of [['all','全部四轮'],...wheels.map((w,i)=>[w,names[i]])]){const o=document.createElement('option');o.value=k;o.textContent=label;this.wheel.append(o)}this.tools.append(this.metric,this.wheel);
   this.snapshot=document.createElement('div');this.snapshot.className='vehicle-snapshot';mount.append(this.snapshot);this.canvas=document.createElement('canvas');this.canvas.className='vehicle-chart';this.canvas.id='vehicle-chart';this.ctx=this.canvas.getContext('2d');mount.append(this.canvas);this.readout=document.createElement('div');this.readout.className='vehicle-readout';mount.append(this.readout);
   this.table=document.createElement('div');this.table.className='vehicle-table';mount.append(this.table);this.note=document.createElement('p');this.note.className='vehicle-note';this.note.textContent='全部与油刹和地图回放时间同步。胎况显示原始 mWear ×100，不等同剩余抓地力；缺失通道显示 —。燃油用量按圈边界估算，进站、无效圈、加油与缺口不用于策略预测。';mount.append(this.note);
   this.metric.onchange=this.wheel.onchange=()=>{this.key='';this.draw(this.time,this.range)};
   this.canvas.onpointermove=e=>{if(!this.onSeek||!this.entries.length)return;const f=Math.max(0,Math.min(1,(e.offsetX-48)/(this.canvas.clientWidth-64)));this.onSeek(this.range[0]+f*(this.range[1]-this.range[0]))};
  }
  setEntries(entries){
   this.entries=entries.map(e=>({...e,bundle:validate(e.bundle)}));this.key='';this.snapshotKey='';const old=this.metric.value;this.metric.replaceChildren();
   for(const [key,label,unit] of metrics){const tyre=!direct.has(key);if(entries.some(e=>e.bundle?.columns.some(k=>tyre?k.endsWith('_'+key):k===key)&&e.bundle.data.some(r=>e.bundle.columns.some((k,i)=>(tyre?k.endsWith('_'+key):k===key)&&r[i+1]!=null)))){const o=document.createElement('option');o.value=key;o.textContent=label+' / '+unit;this.metric.append(o)}}
   if([...this.metric.options].some(o=>o.value===old))this.metric.value=old;
   this.summary();
  }
  summary(){
   this.table.replaceChildren();const records=this.entries.flatMap(e=>e.stint_laps?.map(r=>({label:'第 '+r.number+' 圈',s:r.vehicle_summary,color:e.color}))||[{label:e.label,s:e.bundle?.summary,color:e.color}]);if(!records.some(r=>r.s))return;
   const table=document.createElement('table'),head=document.createElement('tr');for(const text of ['完整圈','耗油 L','VE 消耗百分点',...names.map(n=>n+' 平均中温 °C'),'电量起→终 %']){const th=document.createElement('th');th.textContent=text;head.append(th)}table.append(head);
   for(const r of records){if(!r.s)continue;const tr=document.createElement('tr');tr.style.color=r.color||'#b9d8f4';const s=r.s,values=[r.label,fmt(s.fuel_l_used?.value,3),fmt(s.virtual_energy_pct_used?.value,2),...wheels.map(w=>fmt(s[w+'_middle_c']?.mean)),s.battery_soc_pct?fmt(s.battery_soc_pct.start)+' → '+fmt(s.battery_soc_pct.end):'—'];for(const v of values){const td=document.createElement('td');td.textContent=v;tr.append(td)}table.append(tr)}this.table.append(table);
  }
  draw(time,range){
   this.time=time;this.range=range;this.readout.replaceChildren();const missing=!this.entries.some(e=>e.bundle?.data.length);
   if(missing){this.snapshot.textContent='这份记录没有轮胎／能量通道。升级后的新记录自动采集；旧日志不会补造数据。';this.canvas.hidden=true;this.tools.hidden=true;return}this.canvas.hidden=false;this.tools.hidden=false;
   const snapshotKey=Math.floor(time*10)+':'+this.entries.map(e=>e.id).join('|');if(snapshotKey!==this.snapshotKey){this.snapshotKey=snapshotKey;this.snapshot.replaceChildren();
   for(const e of this.entries){const t=Math.min(time,e.duration??time),v=at(e.bundle,t),box=document.createElement('div');box.className='vehicle-box';box.style.borderColor=e.color||'#30435c';const h=document.createElement('h3');h.textContent=e.label;h.style.color=e.color||'#c7deef';box.append(h);
    const fuel=document.createElement('div');fuel.className='vehicle-value';fuel.textContent='燃油 '+fmt(v.fuel_l,2)+' L';box.append(fuel);const energy=document.createElement('p');energy.className='vehicle-note';energy.textContent='电池 '+fmt(v.battery_soc_pct)+'% · 虚拟能量 '+fmt(v.virtual_energy_pct)+'% · 回收 '+fmt(v.regen_kw)+' kW';box.append(energy);
    if(v.track_temp_c!=null||v.wetness!=null||v.rain_severity!=null){const context=document.createElement('p');context.className='vehicle-note';context.textContent='赛道 '+fmt(v.track_temp_c)+' °C · 湿 '+fmt(v.wetness==null?null:v.wetness*100)+'% · 雨强 '+fmt(v.rain_severity==null?null:v.rain_severity*100)+'% · 胎种序号 '+fmt(v.tyre_front_index,0);box.append(context)}
    if(e.stint_laps){const estimate=fuelEstimate(e,t,v),p=document.createElement('p');p.className='vehicle-note';p.textContent='最近 '+estimate.count+' 圈 · 估算 '+fmt(estimate.rate,3)+' L/圈 · 可跑 '+fmt(estimate.range,2)+' 圈\n目标需 '+fmt(estimate.required,2)+' L · 余量 '+fmt(estimate.margin,2)+' L';if(estimate.margin!=null&&estimate.margin<0)p.classList.add('vehicle-warning');box.append(p)}
    const grid=document.createElement('div');grid.className='vehicle-tyres';for(const [i,w] of wheels.entries()){const cell=document.createElement('div');cell.className='vehicle-wheel';const p=e.bundle?.profile||{},temp=v[w+'_middle_c'],pressure=v[w+'_pressure_kpa'],wear=v[w+'_wear_fraction'];const alerts=[];if(v[w+'_flat'])alerts.push('爆胎');if(v[w+'_detached'])alerts.push('脱落');if(p.alerts){if(temp!=null&&(temp<p.temp_min||temp>p.temp_max))alerts.push('胎温超限');if(pressure!=null&&(pressure<p.pressure_min||pressure>p.pressure_max))alerts.push('胎压超限');if(wear!=null&&wear*100<p.wear_min)alerts.push('胎况低')}
     cell.style.whiteSpace='pre-line';cell.textContent=names[i]+' · '+fmt(pressure)+' kPa\n内 / 中 / 外 '+[v[w+'_inner_c'],temp,v[w+'_outer_c']].map(x=>fmt(x,0)).join(' / ')+' °C\n胎体 '+fmt(v[w+'_carcass_c'])+' °C · 胎况 '+fmt(wear==null?null:wear*100)+'%'+(alerts.length?'\n'+alerts.join(' / '):'');if(alerts.length)cell.classList.add('vehicle-warning');grid.append(cell)}box.append(grid);this.snapshot.append(box);
   }
   }this.plot();
  }
  series(){const m=metrics.find(m=>m[0]===this.metric.value);if(!m)return [];const tyre=!direct.has(m[0]);this.wheel.hidden=!tyre;const series=[];
   this.entries.forEach(e=>{for(const w of tyre?(this.wheel.value==='all'?wheels:[this.wheel.value]):['']){const k=w?w+'_'+m[0]:m[0],i=e.bundle?.columns.indexOf(k);if(i==null||i<0)continue;const points=e.bundle.data.map(r=>[e.project?e.project(r[0]):r[0],r[i+1]==null?null:r[i+1]*m[3],r[0]]);series.push({label:e.label+(w?' / '+w.toUpperCase():''),color:this.entries.length>1?e.color:wheelColors[Math.max(0,wheels.indexOf(w))],dash:this.entries.length>1&&w?[[], [5,3], [10,3], [2,3]][wheels.indexOf(w)]:[],points})}});return series;
  }
  plot(){
   const canvas=this.canvas,ctx=this.ctx,w=Math.max(250,canvas.clientWidth),h=235,dpr=devicePixelRatio||1,m=metrics.find(m=>m[0]===this.metric.value),key=[globalThis.StintLabTheme?.mode||'dark',w,dpr,...this.range,this.metric.value,this.wheel.value,...this.entries.map(e=>e.id)].join('|');
   const series=key===this.key&&this.cachedSeries?this.cachedSeries:this.series();this.cachedSeries=series;
   if(!this.back)this.back=document.createElement('canvas');const bg=this.back.getContext('2d');
   if(key!==this.key){this.key=key;canvas.width=this.back.width=w*dpr;canvas.height=this.back.height=h*dpr;bg.setTransform(dpr,0,0,dpr,0,0);bg.fillStyle=(globalThis.StintLabTheme?.color('CARD')||'#101a28');bg.fillRect(0,0,w,h);let low=Infinity,high=-Infinity;for(const s of series)for(const [x,y] of s.points)if(x>=this.range[0]&&x<=this.range[1]&&y!=null){low=Math.min(low,y);high=Math.max(high,y)}if(!Number.isFinite(low)){low=0;high=1}const pad=Math.max(.1,(high-low)*.08);low-=pad;high+=pad;const x=t=>48+(t-this.range[0])/(this.range[1]-this.range[0])*(w-64),y=v=>199-(v-low)/(high-low)*170;
    bg.font='11px system-ui';for(let i=0;i<5;i++){const value=low+(high-low)*i/4;bg.strokeStyle=(globalThis.StintLabTheme?.color('FIELD')||'#29374a');bg.beginPath();bg.moveTo(48,y(value));bg.lineTo(w-16,y(value));bg.stroke();bg.fillStyle=(globalThis.StintLabTheme?.color('MUTED')||'#92abc9');bg.fillText(value.toFixed(1),2,y(value)+3)}bg.fillText(m?.[2]||'',3,15);bg.fillText(this.entries[0]?.project?'按赛道距离对齐 / m':'按记录时间对齐 / s',48,225);bg.save();bg.beginPath();bg.rect(48,20,w-64,185);bg.clip();
    for(const s of series){bg.strokeStyle=s.color||'#69b8ff';bg.lineWidth=1.5;bg.setLineDash(s.dash);bg.beginPath();let prev=null;for(const p of s.points){if(p[1]==null){prev=null;continue}if(!prev||p[2]-prev[2]>1.5)bg.moveTo(x(p[0]),y(p[1]));else bg.lineTo(x(p[0]),y(p[1]));prev=p}bg.stroke()}bg.restore();bg.setLineDash([]);
   }
   ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(this.back,0,0);ctx.setTransform(dpr,0,0,dpr,0,0);const position=this.entries[0]?.project?this.entries[0].project(this.time):this.time;if(position>=this.range[0]&&position<=this.range[1]){const x=48+(position-this.range[0])/(this.range[1]-this.range[0])*(w-64);ctx.strokeStyle=(globalThis.StintLabTheme?.color('FG')||'#ecf6ff')+'99';ctx.beginPath();ctx.moveTo(x,20);ctx.lineTo(x,199);ctx.stroke()}
   for(const s of series){const span=document.createElement('span');span.style.color=s.color;span.textContent='● '+s.label+'　';this.readout.append(span)}
  }
 }
 return {View,validate,at,fuelEstimate};
})();
