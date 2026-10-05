/* GTD editorial snapshot in the Stintrix industrial shell. All runtime content is local. */
(() => {
 'use strict';
 const aliases={'bahrain':'巴林','barcelona':'巴塞罗那 加泰罗尼亚','le-mans':'勒芒 萨尔特','paul-ricard':'保罗里卡尔','cota':'美洲 奥斯汀','daytona':'代托纳','fuji':'富士','imola':'伊莫拉','interlagos':'英特拉格斯 因特拉格斯','lusail':'卢赛尔 罗赛尔','monza':'蒙扎','portimao':'波尔蒂芒 阿尔加维','sebring':'赛百灵 塞布林','silverstone-international':'银石','spa':'斯帕 弗朗科尔尚','laguna-seca':'拉古纳塞卡','road-atlanta':'亚特兰大之路 罗德亚特兰大','long-beach':'长滩'};
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const safeURL=value=>{try{const u=new URL(value);return u.protocol==='https:'?u.href:'';}catch{return '';}};
 function favorites(value,data){
  const out={tracks:[],cars:[]};
  for(const kind of ['tracks','cars'])out[kind]=[...new Set(Array.isArray(value?.[kind])?value[kind].filter(v=>typeof v==='string'&&Object.hasOwn(data[kind],v)):[])];
  return out;
 }
 function matchRec(rec,filter,favs){return (!filter.group||rec.car_class===filter.group)&&(!filter.car||rec.car_slug===filter.car)&&(filter.favorite!=='cars'||favs.cars.includes(rec.car_slug));}
 function rows(data,view,filter,favs){
  const query=String(filter.query||'').trim().toLocaleLowerCase();
  return Object.values(data[view]).flatMap(item=>{
   const name=[item.name,item.slug,item.car_class,item.location,item.location_zh,aliases[item.slug]].join(' ').toLocaleLowerCase();
   if(query&&!name.includes(query))return [];
   if(view==='cars')return ((!filter.group||item.car_class===filter.group)&&(!filter.car||item.slug===filter.car)&&(!filter.favorite||favs.cars.includes(item.slug)))?[{item}]:[];
   if(filter.favorite==='tracks'&&!favs.tracks.includes(item.slug))return [];
   const recommendations=item.recommendations.filter(r=>matchRec(r,filter,favs));return recommendations.length?[{item,recommendations}]:[];
  });
 }
 const api={esc,safeURL,favorites,rows};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;
 if(typeof document==='undefined')return;
 const data=JSON.parse(document.getElementById('guide-data').textContent),palettes=window.StintrixGuidePalettes;
 const $=id=>document.getElementById(id),root=document.documentElement,key='stintrix-guide-favorites';
 const query=new URLSearchParams(location.hash.slice(1));let view=query.get('view')==='cars'?'cars':'tracks',lang='zh',theme=query.get('theme')==='light'?'light':'dark';
 let favs={tracks:[],cars:[]},storage=false,selected=new Set(),returnFocus=null,requested=query.get('item')||'',limit=false;
 try{favs=favorites(JSON.parse(localStorage.getItem(key)),data);lang=localStorage.getItem('stintrix-guide-language')==='en'?'en':'zh';}catch{storage=true;}
 const tr=(zh,en)=>lang==='en'?en:zh,copy=(item,key)=>item[lang==='en'?key:key+'_zh']||item[key]||'';
 const recs=new Map();for(const track of Object.values(data.tracks))for(const rec of track.recommendations)recs.set('rec:'+rec.key,{track,rec,car:data.cars[rec.car_slug]});
 const links=(url,label)=>{const href=safeURL(url);return href?`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`:'';};
 const media=item=>/^media\/(cars|tracks)\/[a-z0-9-]+\.webp$/.test(item.image)?`<img class="media" src="${esc(item.image)}" width="1024" height="576" alt="${esc(item.name)}" loading="lazy" decoding="async">`:'';
 const button=(action,key,text,pressed=false,cls='')=>`<button type="button" class="${cls}" data-action="${action}" data-key="${esc(key)}" aria-pressed="${pressed}">${esc(text)}</button>`;
 const star=(kind,id)=>button('favorite',kind+':'+id,favs[kind].includes(id)?'★':'☆',favs[kind].includes(id),'star');
 function practice(note){return `<div class="note"><p><strong>${tr('来源摘记：','Source note: ')}</strong>${esc(copy(note,'observation'))}</p><p><strong>${tr('练习建议：','Practice: ')}</strong>${esc(copy(note,'exercise'))}</p><p class="meta">${esc(note.checked_on)} · ${links(note.source_url,note.source_name)}</p></div>`;}
 function review(value){return `<div class="review"><p>${tr('适用游戏版本：','Applicable game version: ')}${esc(value.applicable_version||tr('未验证','Unverified'))} · ${tr('资料检查：','Reviewed: ')}${esc(value.checked_on)}</p>${value.sources.map((url,i)=>links(url,tr('来源 ','Source ')+(i+1))).join(' ')}${value.evidence_url?links(value.evidence_url,tr('实测证据','Driving evidence')):`<span>${tr('暂无该推荐的版本实测证据','No build-specific driving evidence for this recommendation')}</span>`}</div>`;}
 const carCopy=car=>`<p><strong>${tr('优点：','Strengths: ')}</strong>${esc(copy(car,'strength'))}</p><p><strong>${tr('注意事项：','Caveats: ')}</strong>${esc(copy(car,'caution'))}</p>${links(car.source_url,tr('LMU 官方车型资料','Official LMU car page'))}`;
 function recommendation(value,comparison=false){
  const {track,rec,car}=value,id='rec:'+rec.key;
  return `<article class="entry recommendation ${rec.sleeper?'sleeper':''}">${media(car)}<div class="copy"><p class="class-tag">${esc(track.name)} // ${esc(rec.car_class)}</p>${rec.sleeper?'<span class="badge">SLEEPER PICK</span>':''}<h3>${esc(car.name)}</h3><p>${esc(copy(rec,'fit'))}</p>${carCopy(car)}${practice(car.note)}${review(rec.review)}<div class="actions">${comparison?button('remove',id,tr('移出对比','Remove')):star('cars',car.slug)+button('compare',id,selected.has(id)?tr('移出对比','Remove'):tr('加入对比','Compare'),selected.has(id))}</div></div></article>`;
 }
 function catalogCard(car,comparison=false){
  const id='car:'+car.slug;
  return `<article class="entry" id="car--${esc(car.slug)}">${media(car)}<div class="copy"><p class="class-tag">${esc(car.car_class)}</p><div class="heading"><h2>${esc(car.name)}</h2>${comparison?'':star('cars',car.slug)}</div>${carCopy(car)}${practice(car.note)}<div class="actions">${button(comparison?'remove':'compare',id,comparison||selected.has(id)?tr('移出对比','Remove'):tr('加入对比','Compare'),!comparison&&selected.has(id))}</div><details data-car-recommendations="${esc(car.slug)}"><summary>${tr('推荐它的赛道','Recommended at')} · ${car.recommendations.length}</summary><div class="recommendations"></div></details></div></article>`;
 }
 function trackCard(track,recommendations){return `<article class="entry" id="track--${esc(track.slug)}">${media(track)}<div class="copy"><p class="meta">${esc(copy(track,'location'))} · ${esc(track.length_km)} km${track.is_dlc?' · DLC':''}</p><div class="heading"><h2>${esc(track.name)}</h2>${star('tracks',track.slug)}</div><p>${esc(copy(track,'character'))}</p><p>${esc(copy(track,'challenge'))}</p><p>${esc(copy(track,'advice'))}</p>${links(track.source_url,tr('LMU 官方赛道资料','Official LMU circuit page'))}${practice(track.note)}<details data-track-recommendations="${esc(track.slug)}"><summary>${tr('查看车型建议','View car recommendations')} · ${recommendations.length}</summary><div class="recommendations"></div></details></div></article>`;}
 function filter(){return {query:$('search').value,group:$('class').value,car:$('car').value,favorite:$('favorites').value};}
 function renderDetails(detail){
  if(!detail.open)return;const target=detail.querySelector('.recommendations');if(!target)return;
  if(detail.dataset.trackRecommendations){const track=data.tracks[detail.dataset.trackRecommendations];target.innerHTML=track.recommendations.filter(r=>matchRec(r,filter(),favs)).map(rec=>recommendation({track,rec,car:data.cars[rec.car_slug]})).join('');}
  else{const car=data.cars[detail.dataset.carRecommendations];target.innerHTML='<ul class="circuit-links">'+car.recommendations.map(rec=>`<li><a href="#view=tracks&item=${esc(rec.track_slug)}&theme=${theme}">${esc(data.tracks[rec.track_slug].name)}</a>${rec.sleeper?' <span class="badge">SLEEPER PICK</span>':''}<p>${esc(copy(rec,'fit'))}</p>${review(rec.review)}</li>`).join('')+'</ul>';}
 }
 function renderCards(){
  const open=[...document.querySelectorAll('#cards details[open]')].map(n=>n.dataset.trackRecommendations||n.dataset.carRecommendations);
  const visible=rows(data,view,filter(),favs);$('cards').innerHTML=visible.map(v=>view==='cars'?catalogCard(v.item):trackCard(v.item,v.recommendations)).join('');
  for(const detail of document.querySelectorAll('#cards details'))if(open.includes(detail.dataset.trackRecommendations||detail.dataset.carRecommendations)){detail.open=true;renderDetails(detail);}
  $('empty').hidden=visible.length>0;$('results').textContent=view==='cars'?tr(`${visible.length} 台车型`,`${visible.length} cars`):tr(`${visible.length} 条赛道 · ${visible.reduce((n,v)=>n+v.recommendations.length,0)} 条推荐`,`${visible.length} circuits · ${visible.reduce((n,v)=>n+v.recommendations.length,0)} recommendations`);
 }
 function named(id){if(id.startsWith('car:'))return data.cars[id.slice(4)]?.name||'';const value=recs.get(id);return value?value.track.name+' · '+value.car.name+(value.rec.sleeper?' · Sleeper':''):'';}
 function renderComparison(){
  $('selection').hidden=selected.size===0;$('selected').innerHTML=[...selected].map(id=>`<span class="chip">${esc(named(id))}${button('remove',id,'×')}</span>`).join('');
  $('compare').disabled=selected.size<2;$('compare').textContent=tr(`并排对比 (${selected.size}/3)`,`Compare (${selected.size}/3)`);
  $('feedback').textContent=limit?tr('最多对比 3 项，请先移除一项。','Compare up to 3 items. Remove one first.'):tr(`已选 ${selected.size}/3 项，至少选择 2 项。`,`${selected.size}/3 selected. Choose at least 2.`);
  for(const node of document.querySelectorAll('[data-action="compare"]')){const active=selected.has(node.dataset.key);node.setAttribute('aria-pressed',String(active));node.textContent=active?tr('移出对比','Remove'):tr('加入对比','Compare');}
  if($('comparison').open){if(selected.size<2)$('comparison').close();else dialogCards();}
 }
 function dialogCards(){
  $('compare-grid').innerHTML=[...selected].map(id=>id.startsWith('car:')?catalogCard(data.cars[id.slice(4)],true):recommendation(recs.get(id),true)).join('');
  for(const node of $('compare-grid').querySelectorAll('[id]'))node.removeAttribute('id');
 }
 function applyTheme(value){
  theme=value in palettes?value:'dark';root.dataset.theme=theme;root.style.colorScheme=theme;
  for(const [key,value] of Object.entries(palettes[theme]))root.style.setProperty('--'+key.toLowerCase().replace('_','-'),value);
  $('theme').textContent=theme==='dark'?tr('◐ 浅色主题','◐ Light theme'):tr('◑ 深色主题','◑ Dark theme');
 }
 function translations(){
  root.lang=lang==='en'?'en':'zh-CN';document.title=tr('Stintrix · ','Stintrix · ')+(view==='cars'?tr('车型图鉴','Car catalog'):tr('赛道指南','Circuit guide'));
  $('title').textContent=view==='cars'?tr('车型图鉴','Car catalog'):tr('赛道指南','Circuit guide');
  $('intro').textContent=view==='cars'?tr('逐台查看车型优点、注意事项和推荐赛道，选择 2–3 台并排对比。','Explore car strengths, caveats, and recommended circuits; compare 2–3 cars side by side.'):tr('以赛道特性为起点，查看 LMGT3 与 Hypercar 推荐及 Sleeper 之选。','Explore each circuit with LMGT3 and Hypercar recommendations and Sleeper Picks.');
  $('version').textContent=tr('GTD 内容版本：','GTD content release: ')+data.content_version+' · '+tr('资料更新：','Updated: ')+data.updated+' · '+tr('实测验证：','Build-validated: ')+data.validated_recommendations+'/'+data.total_recommendations+' · '+tr('资料参考：','Reference: ')+data.game_reference;
  $('language').textContent=lang==='zh'?'EN':'中文';
  for(const [id,zh,en] of [['search-label','搜索','Search'],['class-label','组别','Class'],['car-label','车型','Car'],['favorites-label','收藏','Favorites'],['reset','重置筛选','Reset filters'],['clear','清空对比','Clear comparison'],['empty','没有匹配的资料，请重置筛选或尝试其他关键词。','No matches. Reset filters or try another search.'],['close','关闭','Close'],['compare-title','并排对比','Side-by-side comparison']])$(id).textContent=tr(zh,en);
  $('search').placeholder=view==='cars'?tr('车型名称…','Car name…'):tr('名称、地点…','Name, location…');
  $('class').options[0].text=tr('全部组别','All classes');$('car').options[0].text=tr('全部车型','All cars');
  $('favorites').options[0].text=tr('全部内容','All content');$('favorites').options[1].text=tr('收藏的赛道','Favorite circuits');$('favorites').options[2].text=tr('收藏的车型','Favorite cars');
  $('favorites').options[1].hidden=view==='cars';
  for(const node of document.querySelectorAll('nav button')){node.textContent=node.dataset.key==='cars'?tr('车型图鉴','Car catalog'):tr('赛道指南','Circuit guide');node.setAttribute('aria-pressed',String(node.dataset.key===view));}
  $('storage-note').hidden=!storage;$('storage-note').textContent=tr('浏览器禁止本地存储；收藏与语言仅在本页会话保留。','Browser storage is unavailable; favorites and language last for this page session.');
  $('attribution').textContent=tr('文字来自 GTD；图片来源 Le Mans Ultimate / Studio 397，保留原资料来源与日期。','Content adapted from GTD; artwork credited to Le Mans Ultimate / Studio 397. Original sources and dates retained.');
  applyTheme(theme);renderCards();renderComparison();
 }
 function switchView(next,item=''){
  const changed=view!==next;view=next==='cars'?'cars':'tracks';requested=item;
  if(changed){selected.clear();limit=false;$('search').value='';$('class').value='';$('car').value='';$('favorites').value='';for(const option of $('car').options)option.hidden=false;}
  translations();
  if(requested&&Object.hasOwn(data[view],requested)){const card=$((view==='cars'?'car--':'track--')+requested);if(card){card.classList.add('highlight');card.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}}
 }
 for(const car of Object.values(data.cars)){const option=document.createElement('option');option.value=car.slug;option.textContent=car.name;option.dataset.class=car.car_class;$('car').append(option);}
 document.addEventListener('toggle',event=>{if(event.target.matches('details'))renderDetails(event.target);},true);
 document.addEventListener('click',event=>{
  const node=event.target.closest('button[data-action]');if(!node)return;
  const action=node.dataset.action,id=node.dataset.key;
  if(action==='view'){location.hash=new URLSearchParams({view:id,theme}).toString();return;}
  if(action==='favorite'){
   const split=id.indexOf(':'),kind=id.slice(0,split),slug=id.slice(split+1);if(!Object.hasOwn(data[kind]||{},slug))return;
   favs[kind]=favs[kind].includes(slug)?favs[kind].filter(v=>v!==slug):[...favs[kind],slug];
   try{localStorage.setItem(key,JSON.stringify(favs));}catch{storage=true;}$('storage-note').hidden=!storage;renderCards();renderComparison();
  }else if(action==='compare'||action==='remove'){
   if(!((id.startsWith('car:')&&Object.hasOwn(data.cars,id.slice(4)))||recs.has(id)))return;
   limit=false;if(selected.has(id))selected.delete(id);else if(action==='compare'&&selected.size<3)selected.add(id);else if(action==='compare')limit=true;
   renderComparison();
  }
 });
 for(const id of ['search','class','car','favorites'])$(id).addEventListener(id==='search'?'input':'change',()=>{
  if(id==='class'){for(const option of $('car').options)option.hidden=!!$('class').value&&!!option.value&&option.dataset.class!==$('class').value;if($('car').selectedOptions[0]?.hidden)$('car').value='';}
  renderCards();
 });
 $('reset').onclick=()=>{for(const id of ['search','class','car','favorites'])$(id).value='';for(const option of $('car').options)option.hidden=false;renderCards();};
 $('clear').onclick=()=>{selected.clear();limit=false;renderComparison();};
 $('compare').onclick=()=>{if(selected.size<2)return;returnFocus=document.activeElement;dialogCards();$('comparison').showModal();$('close').focus();};
 $('close').onclick=()=>$('comparison').close();$('comparison').addEventListener('close',()=>{if(returnFocus?.isConnected)returnFocus.focus();else $('compare').focus();});
 $('language').onclick=()=>{lang=lang==='zh'?'en':'zh';try{localStorage.setItem('stintrix-guide-language',lang);}catch{storage=true;}translations();};
 $('theme').onclick=()=>{applyTheme(theme==='dark'?'light':'dark');renderCards();history.replaceState(null,'','#'+new URLSearchParams({view,theme,...(requested?{item:requested}:{})}));};
 window.addEventListener('hashchange',()=>{const query=new URLSearchParams(location.hash.slice(1));if(['dark','light'].includes(query.get('theme')))theme=query.get('theme');switchView(query.get('view'),query.get('item')||'');});
 window.addEventListener('storage',event=>{if(event.key===key){try{favs=favorites(JSON.parse(event.newValue),data);renderCards();renderComparison();}catch{}}});
 window.StintrixGuide={data,get view(){return view;},get selected(){return [...selected];},get favorites(){return favs;}};
 switchView(view,requested);
})();
