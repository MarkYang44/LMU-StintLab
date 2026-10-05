/* Embedded into reports; works offline and stores no telemetry. */
(() => {
 const palettes=/*UI_PALETTES*/null, fallback=/*UI_MODE*/'dark';
 let mode=palettes[document.documentElement.dataset.theme]?document.documentElement.dataset.theme:fallback;
 try {const saved=localStorage.getItem('stintrix-interface-theme');if(palettes[saved])mode=saved;} catch {}
 const sheet=document.createElement('style');sheet.textContent=`
 html{color-scheme:dark}html[data-theme=light]{color-scheme:light}
 body{background:var(--sl-bg)!important;color:var(--sl-fg)!important}
 .card,section,.lap-card,.vehicle-card,.endurance-card{background:var(--sl-card)!important;border-color:var(--sl-edge)!important;border-radius:3px!important}
 button,select,input,textarea,.file-button{background:var(--sl-field)!important;color:var(--sl-fg)!important;border-color:var(--sl-edge)!important;border-radius:3px!important;accent-color:var(--sl-accent);transition:background .15s,border-color .15s,transform .15s}
 button:hover,.file-button:hover{background:var(--sl-hover)!important;border-color:var(--sl-accent)!important}
 button:active{transform:translateY(1px)}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--sl-accent);outline-offset:3px}
 .primary{background:var(--sl-button)!important;color:var(--sl-ink)!important}
 small,.muted,#meta,.empty,footer,th,.vehicle-note,.endurance-note,#replay-time{color:var(--sl-muted)!important}
 .eyebrow,a{color:var(--sl-accent)!important}td,th,.replay{border-color:var(--sl-edge)!important}
 .green{color:var(--sl-green)!important}.red{color:var(--sl-red)!important}.blue{color:var(--sl-blue)!important}
 section,.card{animation:sl-enter .23s ease-out}#sl-theme{margin:6px 0;white-space:nowrap}
 @keyframes sl-enter{from{opacity:.4;transform:translateY(6px)}to{opacity:1;transform:none}}
 @media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
 `;document.head.append(sheet);
 const theme=window.StintrixTheme={mode,color:key=>palettes[theme.mode][key]};
 function apply(value){
  mode=theme.mode=value;document.documentElement.dataset.theme=value;
  for(const [key,color] of Object.entries(palettes[value]))document.documentElement.style.setProperty('--sl-'+key.toLowerCase().replace('_','-'),color);
  const button=document.getElementById('sl-theme');if(button)button.textContent=value==='dark'?'◐ 浅色主题':'◑ 深色主题';
  window.dispatchEvent(new Event('resize'));
 }
 apply(mode);
 document.addEventListener('DOMContentLoaded',()=>{
  const button=document.getElementById('sl-theme')||document.createElement('button');button.id='sl-theme';button.type='button';button.setAttribute('aria-label','切换深色 / 浅色主题');
  button.onclick=()=>{const next=theme.mode==='dark'?'light':'dark';try{localStorage.setItem('stintrix-interface-theme',next)}catch{}apply(next)};
  (document.querySelector('header')||document.body).append(button);apply(theme.mode);
 });
})();
