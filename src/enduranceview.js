/* Observed pit/stint/weather review, synchronized with the existing timeline. */
const InputScopeEndurance=(()=>{
 const f=(x,n=1)=>Number.isFinite(x)?x.toFixed(n):'—';
 const colors=['#69b8ff','#67e3bc','#ffb86b','#c99aff','#ff8799'];
 const metrics=[['rain_severity','雨量强度','%',100],['wetness','平均赛道湿度','%',100],['wetness_min','最小湿度','%',100],['wetness_max','最大湿度','%',100],['track_temp_c','赛道温度','°C',1],['ambient_temp_c','环境温度','°C',1],['wind_x_raw','风 X（SDK 原值）','未确认单位',1],['wind_z_raw','风 Z（SDK 原值）','未确认单位',1]];
 function node(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
 class View{
  constructor(mount,bundle,analysis,onSeek){
   this.mount=mount;this.bundle=bundle;this.analysis=analysis;this.onSeek=onSeek;this.range=[0,1];this.cache='';this.time=0;this.snapshotKey='';
   mount.replaceChildren();mount.append(node('h2','进站 / Stint / 天气与赛道演变'));
   const style=node('style');style.textContent='.endurance-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:14px 0}.endurance-card{background:var(--sl-card,#101a28);border:1px solid var(--sl-edge,#30435c);border-radius:12px;padding:14px;line-height:1.9}.endurance-table{overflow:auto;margin:12px 0}.endurance-table table{width:100%;min-width:850px;font-size:12px;border-collapse:collapse}.endurance-table td,.endurance-table th{padding:10px;text-align:left;border-bottom:1px solid var(--sl-edge,#2a3b52);white-space:nowrap}.endurance-table button{padding:5px 9px}.endurance-table details{white-space:normal}.endurance-table details button{margin:4px 4px 0 0}.endurance-chart{height:210px!important}.endurance-note{font-size:12px;color:var(--sl-muted,#91a4bf);line-height:1.8}.endurance-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;margin:8px 0}';mount.append(style);
   this.cards=node('div',null,'endurance-cards');mount.append(this.cards);
   if(!bundle||!analysis?.available){mount.append(node('p','这份记录缺少新增进站／天气遥测。已有圈速与油刹复盘仍可使用；新记录会自动采集。','endurance-note'));return}
   mount.append(node('h3','进站事件'));this.table('pit',analysis.pits||[]);
   mount.append(node('p','点击事件跳转到进站时刻。静止是速度阈值统计，包含等候；补给量为连续遥测中的正向增量。损失估算使用受影响完整圈与至少三个相近条件有效圈，不等同官方计时。','endurance-note'));
   mount.append(node('h3','Stint 长距离表现'));this.table('stint',analysis.stints||[]);
   this.paceCanvas=node('canvas',null,'endurance-chart');this.paceCanvas.setAttribute('aria-label','Stint 完整圈圈速趋势');mount.append(this.paceCanvas);
   const legend=node('div',null,'endurance-legend');(analysis.stints||[]).forEach((s,i)=>{const span=node('span','● Stint '+s.number);span.style.color=colors[i%colors.length];legend.append(span)});mount.append(legend);
   mount.append(node('p','暖胎观察仅按每段前 N 个完整有效圈标记。后段变化 = 后段窗口中位数 − 稳定初段窗口中位数，正值表示变慢；两组窗口不得重叠。油量、天气与交通会影响结果，不自动认定轮胎衰退。','endurance-note'));
   const tools=node('div',null,'tools');tools.append(node('h3','天气 / 赛道趋势'));this.select=node('select');this.select.setAttribute('aria-label','天气赛道通道');
   metrics.forEach(([key,label,unit])=>{const j=bundle.columns.indexOf(key)+1;if(j>0&&bundle.data.some(r=>r[j]!=null)){const o=node('option',label+' / '+unit);o.value=key;this.select.append(o)}});tools.append(this.select);mount.append(tools);
   this.canvas=node('canvas',null,'endurance-chart');this.canvas.setAttribute('aria-label','天气随时间变化');mount.append(this.canvas);this.readout=node('div',null,'endurance-note');mount.append(this.readout);
   this.select.onchange=()=>{this.cache='';this.draw(this.time,this.range)};
   for(const c of [this.canvas,this.paceCanvas])c.onpointerdown=e=>{const t=this.range[0]+Math.max(0,Math.min(1,(e.offsetX-58)/(c.clientWidth-78)))*(this.range[1]-this.range[0]);this.onSeek?.(t)};
   const events=node('details');events.append(node('summary','显著天气变化（'+(analysis.weather_alerts||[]).length+'）'));
   for(const a of analysis.weather_alerts||[]){const m=metrics.find(x=>x[0]===a.field)||[a.field,a.field,'',1];const b=node('button',f(a.time_s)+' s · '+m[1]+' '+f(a.from_value*m[3])+' → '+f(a.to_value*m[3])+' '+m[2]);b.onclick=()=>this.onSeek?.(a.time_s);events.append(b)}mount.append(events);
   mount.append(node('p',analysis.note,'endurance-note'));
  }
  table(kind,records){
   const wrap=node('div',null,'endurance-table'),table=node('table');table.id='endurance-'+kind+'-table';const header=node('tr');
   const names=kind==='pit'?['事件 / 跳转','圈','进站→出站 s','总用时 s','静止 s','补油 L','VE 增量百分点','超速 s','估算损失 s','数据状态']:['Stint / 跳转','时间范围 s','完整可用圈','中位圈速 s','圈速波动 s','后段变化 s','初段→后段油量 L','胎种序号 / 条件'];
   names.forEach(s=>header.append(node('th',s)));table.append(header);
   records.forEach((r,i)=>{
    const tr=node('tr'),first=node('td'),b=node('button',String(r.number));b.onclick=()=>this.onSeek?.(kind==='pit'?r.entry_s:r.start_s,[kind==='pit'?r.entry_s:r.start_s,kind==='pit'?r.exit_s||this.analysis.duration_s:r.end_s]);first.append(b);tr.append(first);
    let values;
    if(kind==='pit')values=[String(r.entry_lap??'—')+'→'+String(r.exit_lap??'—'),f(r.entry_s)+' → '+f(r.exit_s),f(r.duration_s),f(r.stationary_s),f(r.fuel_added_l,2),f(r.energy_added_pct,2),(r.limits_used||[]).some(x=>x>0)?f(r.overspeed_s)+(r.limits_used.length>1?'（阈值变更）':''):'未设限速',f(r.estimated_loss_s),r.gap?'遥测缺口':r.partial_start||r.partial_end?'边界不完整':'已完整记录'];
    else{const a=r.laps?.[0]?.context||{},z=r.laps?.at(-1)?.context||{};values=[f(r.start_s)+' → '+f(r.end_s),r.pace?.count??0,f(r.pace?.median_s,2),f(r.pace?.spread_s,2),f(r.pace?.drift_s,2),f(a.fuel_l)+' → '+f(z.fuel_l),String(a.tyre_front_index??'—')+(r.pace?.conditions_changed?' · 条件变化':' · 未发现已知条件变化')];tr.style.color=colors[i%colors.length]}
    values.forEach(v=>tr.append(node('td',String(v))));table.append(tr);
    if(kind==='stint'&&r.laps?.length){const detail=node('tr'),td=node('td');td.colSpan=names.length;const box=node('details');box.append(node('summary','查看第 '+r.number+' 段逐圈油量 / 天气 / 胎种'));
     r.laps.forEach((l,j)=>{const c=l.context||{},line=node('button','L'+l.number+' '+f(l.time_s,2)+' s'+(j<(this.analysis.config?.warmup_laps??2)?' · 暖胎观察':'')+(l.validity&&l.validity!=='verified'?' · 有效性未验证':'')+' · 油 '+f(c.fuel_l)+' L · 赛道 '+f(c.track_temp_c)+' °C · 湿 '+f(c.wetness==null?null:c.wetness*100)+'% · 胎 '+String(c.tyre_front_index??'—'));line.onclick=()=>this.onSeek?.(l.start_time_s,[l.start_time_s,l.end_time_s]);box.append(line)});td.append(box);detail.append(td);table.append(detail)}
   });if(!records.length){const tr=node('tr'),td=node('td','没有已观测事件／完整圈');td.colSpan=names.length;tr.append(td);table.append(tr)}wrap.append(table);this.mount.append(wrap);
  }
  draw(t,range){
   if(!this.canvas)return;this.time=t;this.range=range;const key=(globalThis.StintLabTheme?.mode||'dark')+Math.floor(t*10);
   if(key!==this.snapshotKey){this.snapshotKey=key;this.cards.replaceChildren();const v=InputScopeVehicle.at(this.bundle,t),p=(this.analysis.pits||[]).find(p=>t>=p.entry_s&&(p.exit_s==null||t<=p.exit_s)),s=(this.analysis.stints||[]).find(s=>t>=s.start_s&&t<=s.end_s);
    for(const [title,text] of [['进站状态',p?'第 '+p.number+' 次 · 已过 '+f(t-p.entry_s)+' s'+(p.partial_start?'（记录起点已在坑道）':''):'赛道上 / 未观测到进站'],['Stint',s?'第 '+s.number+' 段 · 燃油 '+f(v.fuel_l)+' L · 胎种序号 '+String(v.tyre_front_index??'—'):'—'],['天气 / 赛道','雨强 '+f(v.rain_severity==null?null:v.rain_severity*100)+'% · 湿 '+f(v.wetness==null?null:v.wetness*100)+'%\n赛道 '+f(v.track_temp_c)+' °C · 环境 '+f(v.ambient_temp_c)+' °C']]){const c=node('div',null,'endurance-card');c.append(node('strong',title),node('div',text));this.cards.append(c)}
   }
   this.plot(this.canvas,false);this.plot(this.paceCanvas,true);
  }
  plot(canvas,pace){
   const w=Math.max(280,canvas.clientWidth),h=210,dpr=devicePixelRatio||1,ctx=canvas.getContext('2d'),metric=metrics.find(m=>m[0]===this.select.value),key=[globalThis.StintLabTheme?.mode||'dark',w,dpr,...this.range,this.select.value].join('|');
   let back=pace?this.paceBack:this.back;if(!back){back=document.createElement('canvas');if(pace)this.paceBack=back;else this.back=back}
   if(back.dataset.key!==key){
    back.dataset.key=key;canvas.width=back.width=w*dpr;canvas.height=back.height=h*dpr;const bg=back.getContext('2d');bg.setTransform(dpr,0,0,dpr,0,0);bg.fillStyle=(globalThis.StintLabTheme?.color('CARD')||'#101a28');bg.fillRect(0,0,w,h);
    const series=pace?(this.analysis.stints||[]).map((s,i)=>({color:colors[i%colors.length],points:s.laps.map(l=>[l.end_time_s,l.time_s]),pace:true})):metric?[{color:'#69b8ff',points:this.bundle.data.map(r=>[r[0],r[this.bundle.columns.indexOf(metric[0])+1]==null?null:r[this.bundle.columns.indexOf(metric[0])+1]*metric[3]])}]:[];
    let lo=Infinity,hi=-Infinity;for(const s of series)for(const p of s.points)if(p[0]>=this.range[0]&&p[0]<=this.range[1]&&p[1]!=null){lo=Math.min(lo,p[1]);hi=Math.max(hi,p[1])}if(!Number.isFinite(lo)){lo=0;hi=1}const pad=Math.max(.1,(hi-lo)*.08);lo-=pad;hi+=pad;
    const x=t=>58+(t-this.range[0])/Math.max(.001,this.range[1]-this.range[0])*(w-78),y=v=>178-(v-lo)/(hi-lo)*150;bg.font='11px system-ui';bg.fillStyle=(globalThis.StintLabTheme?.color('MUTED')||'#91a4bf');bg.fillText(pace?'完整有效圈圈速 / s':metric?metric[1]+' / '+metric[2]:'没有可用天气通道',58,16);
    for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3;bg.strokeStyle=(globalThis.StintLabTheme?.color('FIELD')||'#29374a');bg.beginPath();bg.moveTo(58,y(v));bg.lineTo(w-20,y(v));bg.stroke();bg.fillText(f(v),3,y(v)+4)}
    bg.save();bg.beginPath();bg.rect(58,22,w-78,161);bg.clip();for(const s of series){bg.strokeStyle=s.color;bg.lineWidth=1.8;bg.beginPath();let prev=null;for(const p of s.points){if(p[1]==null){prev=null;continue}if(!prev||!s.pace&&p[0]-prev[0]>1.5)bg.moveTo(x(p[0]),y(p[1]));else bg.lineTo(x(p[0]),y(p[1]));prev=p}bg.stroke();if(s.pace){bg.fillStyle=s.color;for(const p of s.points){bg.beginPath();bg.arc(x(p[0]),y(p[1]),3,0,Math.PI*2);bg.fill()}}}bg.restore();bg.fillText(f(this.range[0])+' s',58,203);bg.fillText(f(this.range[1])+' s',w-72,203);
   }
   ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(back,0,0);ctx.setTransform(dpr,0,0,dpr,0,0);if(this.time>=this.range[0]&&this.time<=this.range[1]){const x=58+(this.time-this.range[0])/Math.max(.001,this.range[1]-this.range[0])*(w-78);ctx.strokeStyle=(globalThis.StintLabTheme?.color('FG')||'#eef4ff')+'99';ctx.beginPath();ctx.moveTo(x,22);ctx.lineTo(x,183);ctx.stroke()}
   if(!pace){const v=InputScopeVehicle.at(this.bundle,this.time);this.readout.textContent=metric?f(this.time)+' s · '+metric[1]+' '+f(v[metric[0]]==null?null:v[metric[0]]*metric[3])+' '+metric[2]:'缺失天气通道'}
  }
 }
 return {View};
})();
