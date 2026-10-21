/* Charts use statement totals and period averages, never invented daily meter readings. */
const Charts = (()=>{
  const number=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:1});
  const money=n=>Number(n).toLocaleString('en-US',{style:'currency',currency:'USD'});
  const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function values(row,metric){return {current:metric==='daily'?row.kwh/row.days:metric==='kwh'?row.kwh:row.total,prior:metric==='kwh'&&row.prior_year_kwh>0?row.prior_year_kwh:metric==='daily'&&row.prior_year_kwh>0&&row.prior_year_days>0?row.prior_year_kwh/row.prior_year_days:null};}
  function label(row,metric){const v=values(row,metric),unit=metric==='daily'?' kWh/day':metric==='kwh'?' kWh':'';return `${new Date(row.end+'T12:00:00').toLocaleDateString('en-US',{month:'short',year:'numeric'})}: ${metric==='total'?money(v.current):number(v.current)+unit}${metric==='total'?'':`; last year ${v.prior===null?'unavailable':number(v.prior)+unit}`}`;}
  function usage(target,rows,selected,metric,events){
    if(!rows.length){target.innerHTML='<p>No statements in this range.</p>';return;}
    const largest=Math.max(1,...rows.flatMap(r=>{const v=values(r,metric);return [v.current,v.prior||0];}));
    const unit=Math.pow(10,Math.floor(Math.log10(largest)));const top=Math.ceil(largest/unit)*unit;
    const ticks=Array.from({length:5},(_,i)=>i*top/4);
    const axis=ticks.map(v=>`<span style="bottom:${v/top*100}%">${metric==='total'?'$':''}${number(v)}</span>`).join('');
    const lines=ticks.slice(1).map(v=>`<span class="gridline" style="bottom:${v/top*100}%"></span>`).join('');
    const bars=rows.map(r=>{const v=values(r,metric);return `<button class="period-column ${selected===r.end?'selected':''}" type="button" data-period="${r.end}" aria-pressed="${selected===r.end}" aria-label="${esc(label(r,metric))}" title="${esc(label(r,metric))}"><span class="bar" style="height:${v.current/top*88}%"><span class="bar-value">${number(v.current)}</span></span>${metric==='total'?'':v.prior===null?'<span class="bar-na">N/A</span>':`<span class="bar prior" style="height:${v.prior/top*88}%"><span class="bar-value">${number(v.prior)}</span></span>`}</button>`;}).join('');
    // 88% usable plot height leaves room for value labels; ticks share the same scale.
    const scaledAxis=ticks.map(v=>`<span style="bottom:${v/top*88}%">${metric==='total'?'$':''}${number(v)}</span>`).join('');
    const scaledLines=ticks.slice(1).map(v=>`<span class="gridline" style="bottom:${v/top*88}%"></span>`).join('');
    target.innerHTML=`<div class="y-axis" aria-hidden="true">${scaledAxis}</div><div class="plot-scroll" style="--periods:${rows.length}"><div class="plot">${scaledLines}${bars}</div><div class="x-axis">${rows.map(r=>{const eventCount=events.filter(e=>e.start<r.end&&e.end>=r.start).length;return `<span>${new Date(r.end+'T12:00:00').toLocaleDateString('en-US',{month:'short'})}<br>${r.end.slice(2,4)}${eventCount?`<i class="event-dot" title="${eventCount} household event(s)"></i>`:''}</span>`;}).join('')}</div></div>`;
    const selectedButton=target.querySelector('.selected');const scroll=target.querySelector('.plot-scroll');if(selectedButton)scroll.scrollLeft=Math.max(0,selectedButton.offsetLeft-scroll.clientWidth/2+selectedButton.clientWidth/2);
  }
  function weather(target,days,priorDays=[],currentStart,priorStart){
    const all=[...days,...priorDays];
    if(!all.length){target.innerHTML='<p class="small">No weather is cached for either period yet. Refresh weather to fetch both years.</p>';return;}
    const w=1000,h=220,left=45,right=15,top=15,bottom=35;
    const low=Math.floor(Math.min(...all.map(d=>d.mean_f))/10)*10-5,high=Math.ceil(Math.max(...all.map(d=>d.mean_f))/10)*10+5;
    const offset=(d,start)=>(new Date(d.day+'T12:00:00Z')-new Date(start+'T12:00:00Z'))/86400000;
    const series=[{days,start:currentStart||days[0]?.day,name:'This period',color:'var(--weather)',dash:''},{days:priorDays,start:priorStart||priorDays[0]?.day,name:'Year ago',color:'var(--prior)',dash:'stroke-dasharray="7 5"'}];
    const span=Math.max(1,...series.flatMap(s=>s.days.map(d=>offset(d,s.start))));
    const x=(d,start)=>left+offset(d,start)/span*(w-left-right),y=t=>h-bottom-(t-low)/(high-low)*(h-top-bottom);
    const grid=Array.from({length:4},(_,i)=>low+(high-low)*i/3).map(t=>`<line class="grid" x1="${left}" x2="${w-right}" y1="${y(t)}" y2="${y(t)}"/><text x="${left-7}" y="${y(t)+4}" text-anchor="end">${Math.round(t)}°F</text>`).join('');
    const paths=series.map(s=>{const path=s.days.map((d,i)=>`${i&&offset(d,s.start)-offset(s.days[i-1],s.start)===1?'L':'M'}${x(d,s.start).toFixed(1)},${y(d.mean_f).toFixed(1)}`).join(' ');return `<path fill="none" stroke="${s.color}" stroke-width="2.5" ${s.dash} d="${path}"/>`+s.days.map(d=>`<circle cx="${x(d,s.start)}" cy="${y(d.mean_f)}" r="3" fill="${s.color}"><title>${s.name}, ${d.day}: mean ${number(d.mean_f)}°F, low ${number(d.low_f)}°F, high ${number(d.high_f)}°F</title></circle>`).join('');}).join('');
    target.innerHTML=`<svg class="weather-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="Daily mean outdoor temperatures: current period and year ago, aligned by service day"><title>Current and prior-year temperatures in °F</title>${grid}${paths}<text x="${left}" y="${h-8}">Service day 1</text><text x="${w-right}" y="${h-8}" text-anchor="end">Service day ${span+1}</text></svg>`;
  }
  return {usage,weather,values,label};
})();
